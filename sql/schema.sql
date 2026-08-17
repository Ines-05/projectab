-- ============================================================
-- backend/speech/sql/schema.sql
-- Fresh schema for the retail-inventory voice agent.
-- Idempotent: safe to re-run against a project that already has it applied.
-- ============================================================

create extension if not exists pg_trgm;
create extension if not exists pgcrypto; -- for gen_random_uuid()

-- ------------------------------------------------------------
-- Tables
-- ------------------------------------------------------------

create table if not exists products (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    category        text,                       -- optional, informational only
    stock_quantity  integer not null default 0 check (stock_quantity >= 0),
    expiration_date date,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (name)
);

create index if not exists products_name_trgm_idx
    on products using gin (name gin_trgm_ops);

create table if not exists sales (
    id          uuid primary key default gen_random_uuid(),
    product_id  uuid not null references products(id),
    quantity    integer not null check (quantity > 0),
    sold_at     timestamptz not null default now()
);

create index if not exists sales_product_id_idx on sales(product_id);

alter table products enable row level security;
alter table sales enable row level security;
-- No policies added: anon/authenticated callers are denied by default.
-- The agent connects with the service_role key, which bypasses RLS.

-- ------------------------------------------------------------
-- match_product: fuzzy name lookup used by the voice tools
-- ------------------------------------------------------------

create or replace function match_product(
    search_term     text,
    match_threshold float default 0.3,
    match_count     int   default 5
)
returns table (
    id              uuid,
    name            text,
    category        text,
    stock_quantity  integer,
    expiration_date date,
    similarity      float
)
language sql
stable
as $$
    -- word_similarity(search_term, name), not similarity(name, search_term):
    -- plain similarity() penalizes heavily when a short spoken query is
    -- compared against a long product name (e.g. "coke" vs "Coca-Cola
    -- Classic 500ml" scores ~0.08 - well below any usable threshold).
    -- word_similarity() instead scores the best-matching word-bounded
    -- substring of the longer string, which is what "does this short
    -- query refer to this product" actually needs (same examples score
    -- ~0.4-0.7 with word_similarity).
    select
        p.id,
        p.name,
        p.category,
        p.stock_quantity,
        p.expiration_date,
        word_similarity(search_term, p.name) as similarity
    from products p
    where word_similarity(search_term, p.name) >= match_threshold
    order by similarity desc
    limit match_count;
$$;

-- ------------------------------------------------------------
-- record_sale: atomic insert-into-sales + stock decrement
-- ------------------------------------------------------------

create or replace function record_sale(
    p_product_id uuid,
    p_quantity   integer
)
returns table (
    id             uuid,
    name           text,
    stock_quantity integer
)
language plpgsql
as $$
declare
    v_current_stock integer;
    v_name          text;
begin
    if p_quantity <= 0 then
        raise exception 'Quantity must be a positive number' using errcode = '22023';
    end if;

    -- Row lock held for the remainder of this function call, serializing
    -- concurrent record_sale() calls against the same product row.
    select products.stock_quantity, products.name
      into v_current_stock, v_name
      from products
     where products.id = p_product_id
       for update;

    if not found then
        raise exception 'Product with id % was not found', p_product_id using errcode = 'P0002';
    end if;

    if v_current_stock < p_quantity then
        raise exception
            'Insufficient stock for %: requested %, only % available',
            v_name, p_quantity, v_current_stock
            using errcode = 'P0001', hint = 'insufficient_stock';
    end if;

    insert into sales (product_id, quantity) values (p_product_id, p_quantity);

    -- RHS explicitly qualified: this function's RETURNS TABLE clause makes
    -- "stock_quantity" an OUT-parameter name in scope here too, which would
    -- otherwise shadow the products.stock_quantity column and raise
    -- "column reference is ambiguous".
    update products
       set stock_quantity = products.stock_quantity - p_quantity,
           updated_at = now()
     where products.id = p_product_id;

    return query
        select products.id, products.name, products.stock_quantity
          from products
         where products.id = p_product_id;
end;
$$;

-- ------------------------------------------------------------
-- execute_readonly_query, for the query_inventory tool.
--
-- Defense in depth: even if an LLM-generated query somehow contains a
-- disguised write/DDL statement past the text-level guard in nl2sql.py,
-- execution fails, because the query runs inside a transaction that has
-- SET LOCAL transaction_read_only = on. This is a Postgres engine-level
-- guarantee, not a grant/role check: ANY data-modifying statement fails
-- here, including one reached indirectly by calling another function
-- (e.g. "select record_sale(...)" disguised as a read) - so, unlike a
-- role/grant-based approach, there's no risk of forgetting to revoke a
-- future write-capable function's default PUBLIC execute grant.
--
-- (An earlier version of this function used SET LOCAL ROLE to a
-- restricted role instead - Postgres explicitly disallows changing role
-- inside a SECURITY DEFINER function, so that approach doesn't work here.)
-- ------------------------------------------------------------

create or replace function execute_readonly_query(query text)
returns json
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    result json;
begin
    set local transaction_read_only = on;
    execute format('select coalesce(json_agg(t), ''[]''::json) from (%s) t', query) into result;
    return result;
end;
$$;

revoke all on function execute_readonly_query(text) from public;

-- service_role only exists on real Supabase projects (auto-created), not on a
-- plain local/scratch Postgres used for schema/RPC testing, so this grant is
-- conditional rather than assumed.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        grant execute on function execute_readonly_query(text) to service_role;
    end if;
end
$$;

-- ------------------------------------------------------------
-- Seed data - one product per shelf-vision classifier category, kept
-- for demo-catalog coherence. Matching is by free-text product name
-- (Gemini's description + match_product), not by these category labels.
-- Nissin Cup Noodles (stock 3) and Amul Gold Milk (expires in 1 day) are
-- deliberately seeded to already breach the default alert thresholds
-- (LOW_STOCK_THRESHOLD=5, EXPIRY_WARNING_DAYS=3) so the alert smoke test
-- doesn't need live data edits.
-- ------------------------------------------------------------

insert into products (name, category, stock_quantity, expiration_date) values
    ('Johnnie Walker Red Label Whisky 750ml',        'alcohol',           24, '2028-01-01'),
    ('Werther''s Original Hard Candy 12oz',           'candy',             40, '2027-06-01'),
    ('Campbell''s Chicken Noodle Soup 305g',          'canned_food',       30, '2027-03-01'),
    ('Snickers Peanut Chocolate Bar 51g',             'chocolate',         50, '2026-12-01'),
    ('Oreo Original Sandwich Cookies 137g',           'dessert',           35, '2026-11-01'),
    ('Betty Crocker Instant Mashed Potatoes 200g',    'dried_food',        20, '2027-05-01'),
    ('Sun-Maid Raisins 425g',                         'dried_fruit',       18, '2027-01-01'),
    ('Coca-Cola Classic 500ml',                       'drink',             60, '2027-02-01'),
    ('Wrigley''s Extra Spearmint Chewing Gum 15pc',   'gum',               45, '2027-09-01'),
    ('Nescafe 3in1 Instant Coffee Mix 20 Sticks',      'instant_drink',     22, '2027-04-01'),
    ('Nissin Cup Noodles Chicken Flavor 64g',          'instant_noodles',   3,  (current_date + interval '2 days')::date),
    ('Amul Gold Full Cream Milk 500ml',               'milk',              4,  (current_date + interval '1 day')::date),
    ('Colgate Total Toothpaste 150g',                 'personal_hygiene',  28, '2028-06-01'),
    ('Lay''s Classic Potato Chips 184g',               'puffed_food',       33, '2026-10-01'),
    ('Kikkoman Soy Sauce 296ml',                       'seasoner',          15, '2027-08-01'),
    ('Bic Cristal Ballpoint Pens 10-Pack',             'stationery',        50, null),
    ('Kleenex Facial Tissues 160ct',                   'tissue',            26, null)
on conflict (name) do nothing;
