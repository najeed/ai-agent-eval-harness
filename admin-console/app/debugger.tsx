import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useEffect, useState } from 'react';
import { Activity } from 'lucide-react-native';

export default function Debugger() {
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://127.0.0.1:5000/api/debugger/state')
      .then(res => res.json())
      .then(data => {
        setState(data);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load debugger state', err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <View style={styles.loaderContainer}>
        <ActivityIndicator size="large" color="#007BFF" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Visual Debugger</Text>
      <View style={styles.card}>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 16 }}>
          <Activity color="#FFC107" size={32} style={{ marginRight: 12 }} />
          <Text style={styles.title}>Real-time Agent State</Text>
        </View>
        <Text style={styles.text}>Status: {state?.message || 'Disconnected'}</Text>
        <View style={styles.codeBlock}>
           <Text style={styles.codeText}>{JSON.stringify(state?.state || {}, null, 2)}</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff', marginBottom: 20 },
  card: { backgroundColor: '#222', padding: 24, borderRadius: 12, borderWidth: 1, borderColor: '#333' },
  title: { fontSize: 22, fontWeight: '600', color: '#fff' },
  text: { color: '#AAA', fontSize: 16, marginBottom: 16 },
  codeBlock: { backgroundColor: '#000', padding: 16, borderRadius: 8, marginTop: 10 },
  codeText: { color: '#00FF41', fontFamily: 'monospace', fontSize: 14 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' }
});
