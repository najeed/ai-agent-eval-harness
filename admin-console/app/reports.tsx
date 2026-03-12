import { View, Text, StyleSheet, FlatList, ActivityIndicator, TextInput, TouchableOpacity } from 'react-native';
import { useEffect, useState } from 'react';
import { BarChart2, Search, ExternalLink } from 'lucide-react-native';
import { router } from 'expo-router';

export default function Reports() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  const fetchRuns = () => {
    setLoading(true);
    fetch(`http://127.0.0.1:5000/api/runs?q=${encodeURIComponent(query)}`)
      .then(res => res.json())
      .then(data => {
        setRuns(data.runs || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load runs', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      fetchRuns();
    }, 300);
    return () => clearTimeout(delayDebounceFn);
  }, [query]);

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
      
      <View style={styles.searchSection}>
        <Search color="#AAA" size={20} style={{ marginRight: 10 }} />
        <TextInput
          style={styles.searchInput}
          placeholder="Search traces..."
          placeholderTextColor="#666"
          value={query}
          onChangeText={setQuery}
        />
      </View>

      <FlatList
        data={runs}
        keyExtractor={(item, idx) => item.run_id || String(idx)}
        renderItem={({ item }) => (
          <TouchableOpacity 
            style={styles.card} 
            onPress={() => router.push({ pathname: '/debugger', params: { run_id: item.run_id } })}
          >
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <BarChart2 color="#28A745" size={24} style={{ marginRight: 10 }} />
                <Text style={styles.title}>Run: {item.run_id}</Text>
              </View>
              <ExternalLink color="#007BFF" size={20} />
            </View>
            <Text style={styles.text}>Scenario: <Text style={{ color: '#FFF' }}>{item.scenario}</Text></Text>
            <Text style={styles.text}>Timestamp: {item.timestamp}</Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff', marginBottom: 20 },
  searchSection: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#222', borderRadius: 12, paddingHorizontal: 15, marginBottom: 16, borderWidth: 1, borderColor: '#333' },
  searchInput: { flex: 1, color: '#FFF', height: 45, fontSize: 16 },
  card: { backgroundColor: '#1A1A1A', padding: 20, borderRadius: 12, marginBottom: 16, borderWidth: 1, borderColor: '#333' },
  title: { fontSize: 18, fontWeight: '600', color: '#fff' },
  text: { color: '#AAA', fontSize: 14, marginBottom: 4 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' }
});
