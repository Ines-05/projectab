import React from 'react';
import { StatusBar } from 'expo-status-bar';
import ConnectionScreen from './src/ConnectionScreen';

export default function App() {
  return (
    <>
      <StatusBar style="light" />
      <ConnectionScreen />
    </>
  );
}
