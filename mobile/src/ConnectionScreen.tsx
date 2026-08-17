import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import {
  AudioSession,
  LiveKitRoom,
  VideoTrack,
  useConnectionState,
  useDataChannel,
  useLocalParticipant,
  useTracks,
} from '@livekit/react-native';
import { ConnectionState, Track } from 'livekit-client';
import { API_BASE_URL } from './config';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

type ScreenState = 'idle' | 'fetching_token' | 'connected' | 'error';

// Topic the agent uses to tell this client to turn its camera on - see
// speech/tools.py's identify_product, which sends this right before it
// needs a frame (folded into "what is this", no separate voice command).
const CAMERA_CONTROL_TOPIC = 'camera-control';

// How long to show the camera preview before switching back to the mic
// icon. Comfortably covers the agent's own camera-warmup wait plus the
// vision/match round trip, so the preview is gone by the time the agent
// starts speaking the result.
const CAMERA_PREVIEW_DURATION_MS = 6000;

export default function ConnectionScreen() {
  const [screenState, setScreenState] = useState<ScreenState>('idle');
  const [details, setDetails] = useState<ConnectionDetails | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    AudioSession.startAudioSession();
    return () => {
      AudioSession.stopAudioSession();
    };
  }, []);

  const connect = useCallback(async () => {
    setErrorMessage(null);
    setScreenState('fetching_token');
    try {
      const participantName = `mobile-${Math.random().toString(36).slice(2, 10)}`;
      const response = await fetch(
        `${API_BASE_URL}/token?participant_name=${encodeURIComponent(participantName)}`,
      );
      if (!response.ok) {
        throw new Error(`Token request failed with status ${response.status}`);
      }
      const data: ConnectionDetails = await response.json();
      setDetails(data);
      setScreenState('connected');
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
      setScreenState('error');
    }
  }, []);

  const disconnect = useCallback(() => {
    setDetails(null);
    setScreenState('idle');
  }, []);

  if (screenState === 'connected' && details) {
    return (
      <LiveKitRoom
        serverUrl={details.serverUrl}
        token={details.participantToken}
        connect
        audio
        video={false}
        style={styles.container}
      >
        <ActiveCallView onDisconnect={disconnect} />
      </LiveKitRoom>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Inventory Voice Assistant</Text>

      {screenState === 'error' && (
        <Text style={styles.errorText}>Couldn't connect: {errorMessage}</Text>
      )}

      <Pressable
        style={styles.connectButton}
        onPress={connect}
        disabled={screenState === 'fetching_token'}
      >
        <Text style={styles.connectButtonText}>
          {screenState === 'fetching_token' ? 'Connecting...' : 'Connect'}
        </Text>
      </Pressable>
    </View>
  );
}

function ActiveCallView({ onDisconnect }: { onDisconnect: () => void }) {
  const connectionState = useConnectionState();
  const { localParticipant } = useLocalParticipant();
  const [showCameraPreview, setShowCameraPreview] = useState(false);
  const revertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cameraTracks = useTracks([Track.Source.Camera]);
  const localCameraTrack = cameraTracks.find((t) => t.participant.isLocal);

  // The camera stays off until the agent asks for it (folded into the
  // identify_product tool, not a separate voice command). On that signal:
  // show the camera preview briefly so the user can confirm the product is
  // actually in frame, then automatically switch back to the mic icon and
  // turn the camera off again.
  useDataChannel(CAMERA_CONTROL_TOPIC, () => {
    localParticipant.setCameraEnabled(true, { facingMode: 'environment' });
    setShowCameraPreview(true);

    if (revertTimer.current) {
      clearTimeout(revertTimer.current);
    }
    revertTimer.current = setTimeout(() => {
      setShowCameraPreview(false);
      localParticipant.setCameraEnabled(false);
    }, CAMERA_PREVIEW_DURATION_MS);
  });

  useEffect(() => {
    return () => {
      if (revertTimer.current) {
        clearTimeout(revertTimer.current);
      }
    };
  }, []);

  const isListening = connectionState === ConnectionState.Connected;
  const statusLabel =
    connectionState === ConnectionState.Connected
      ? showCameraPreview
        ? 'Looking at the product...'
        : 'Listening'
      : connectionState === ConnectionState.Connecting
        ? 'Connecting...'
        : connectionState === ConnectionState.Reconnecting
          ? 'Reconnecting...'
          : 'Disconnected';

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Inventory Voice Assistant</Text>

      {showCameraPreview && localCameraTrack ? (
        <VideoTrack trackRef={localCameraTrack} style={styles.cameraPreview} />
      ) : (
        <View style={[styles.micCircle, isListening && styles.micCircleActive]}>
          <Text style={styles.micIcon}>🎙️</Text>
        </View>
      )}

      <Text style={styles.statusText}>{statusLabel}</Text>

      <Pressable style={styles.disconnectButton} onPress={onDisconnect}>
        <Text style={styles.connectButtonText}>Disconnect</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#111318',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 20,
  },
  title: {
    color: '#ffffff',
    fontSize: 22,
    fontWeight: '600',
    textAlign: 'center',
  },
  statusText: {
    color: '#9aa0ab',
    fontSize: 16,
  },
  errorText: {
    color: '#ff6b6b',
    fontSize: 14,
    textAlign: 'center',
  },
  connectButton: {
    backgroundColor: '#3b82f6',
    paddingVertical: 16,
    paddingHorizontal: 40,
    borderRadius: 999,
  },
  disconnectButton: {
    backgroundColor: '#ef4444',
    paddingVertical: 16,
    paddingHorizontal: 40,
    borderRadius: 999,
  },
  connectButtonText: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: '600',
  },
  micCircle: {
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: '#1c1f26',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 3,
    borderColor: '#2a2f3a',
  },
  micCircleActive: {
    backgroundColor: '#1e3a8a',
    borderColor: '#3b82f6',
  },
  micIcon: {
    fontSize: 72,
  },
  cameraPreview: {
    width: 240,
    height: 320,
    borderRadius: 16,
    backgroundColor: '#1c1f26',
    overflow: 'hidden',
  },
});
