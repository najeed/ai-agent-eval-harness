import { View, Text, StyleSheet, FlatList, ActivityIndicator } from 'react-native';
import { useEffect, useState } from 'react';
import { BarChart2 } from 'lucide-react-native';

export default function Reports() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://127.0.0.1:5000/api/runs')
      .then(res => res.json())
      .then(data => {
        setRuns(data.runs || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load runs', err);
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
      <Text style={styles.header}>Evaluation Traces</Text>
      <FlatList
        data={runs}
        keyExtractor={(item, idx) => item.run_id || String(idx)}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
              <BarChart2 color="#28A745" size={24} style={{ marginRight: 10 }} />
              <Text style={styles.title}>Run: {item.run_id}</Text>
            </View>
            <Text style={styles.text}>Scenario: {item.scenario}</Text>
            <Text style={styles.text}>Timestamp: {item.timestamp}</Text>
          </View>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff', marginBottom: 20 },
  card: { backgroundColor: '#222', padding: 20, borderRadius: 12, marginBottom: 16, borderWidth: 1, borderColor: '#333' },
  title: { fontSize: 18, fontWeight: '600', color: '#fff' },
  text: { color: '#AAA', fontSize: 14, marginBottom: 4 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' }
});
