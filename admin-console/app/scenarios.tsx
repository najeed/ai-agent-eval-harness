import { View, Text, StyleSheet, FlatList, ActivityIndicator, TouchableOpacity } from 'react-native';
import { useEffect, useState } from 'react';
import { FileText } from 'lucide-react-native';

export default function Scenarios() {
  const [scenarios, setScenarios] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://127.0.0.1:5000/api/scenarios')
      .then(res => res.json())
      .then(data => {
        setScenarios(data.scenarios || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load scenarios', err);
        setLoading(false);
      });
  }, []);

  const handleRun = (path: string) => {
    fetch('http://127.0.0.1:5000/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    }).then(res => res.json()).then(data => alert(data.message));
  };

  if (loading) {
    return (
      <View style={styles.loaderContainer}>
        <ActivityIndicator size="large" color="#007BFF" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Scenarios Library</Text>
      <FlatList
        data={scenarios}
        keyExtractor={item => item.scenario_id}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
              <FileText color="#007BFF" size={24} style={{ marginRight: 10 }} />
              <Text style={styles.title}>{item.title}</Text>
            </View>
            <Text style={styles.text}>ID: {item.scenario_id}</Text>
            <Text style={styles.text}>Industry: {item.industry}</Text>
            <TouchableOpacity style={styles.button} onPress={() => handleRun(item.file_path)}>
              <Text style={styles.buttonText}>Run Evaluation</Text>
            </TouchableOpacity>
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
  button: { marginTop: 12, backgroundColor: '#007BFF', padding: 10, borderRadius: 8, alignItems: 'center' },
  buttonText: { color: '#fff', fontWeight: 'bold' },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' }
});
