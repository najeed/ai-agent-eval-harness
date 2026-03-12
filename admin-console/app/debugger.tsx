import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, TextInput, ScrollView } from 'react-native';
import { useEffect, useState } from 'react';
import { Activity, RefreshCw, Search } from 'lucide-react-native';
import { useLocalSearchParams } from 'expo-router';

export default function Debugger() {
  const { run_id } = useLocalSearchParams();
  const [state, setState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const fetchState = () => {
    setLoading(true);
    // Optionally clear current state to show full loader, or keep it to avoid flicker
    // setState(null); 
    const url = run_id 
      ? `http://127.0.0.1:5000/api/debugger/state?run_id=${run_id}`
      : 'http://127.0.0.1:5000/api/debugger/state';
      
    fetch(url)
      .then(res => res.json())
      .then(data => {
        setState(data);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load debugger state', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchState();
  }, [run_id]);

  const highlightText = (text: string) => {
    if (!search) return text;
    // Simple text-only highlight logic is hard in React Native Text, 
    // but we can at least show it is being filtered if we were doing a list.
    // For now we'll just keep the search state.
    return text;
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
      <View style={styles.headerRow}>
        <Text style={styles.header}>{run_id ? `Trace: ${run_id}` : 'Visual Debugger'}</Text>
        <TouchableOpacity style={styles.reloadBtn} onPress={fetchState}>
          <RefreshCw color="#007BFF" size={20} />
          <Text style={styles.reloadText}>Reload</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.searchBar}>
        <Search color="#888" size={18} style={{ marginRight: 8 }} />
        <TextInput 
          style={styles.searchInput}
          placeholder="Search in state..."
          placeholderTextColor="#666"
          value={search}
          onChangeText={setSearch}
        />
      </View>

      <ScrollView showsVerticalScrollIndicator={false}>
      <View style={styles.card}>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 16 }}>
          <Activity color="#FFC107" size={32} style={{ marginRight: 12 }} />
          <Text style={styles.title}>Real-time Agent State</Text>
        </View>
        <Text style={styles.text}>Status: {state?.data?.message || 'Disconnected'}</Text>
        <Text style={styles.label}>Context: <Text style={{ color: '#FFF' }}>{state?.data?.current_agent || 'N/A'}</Text></Text>
        
        {state?.data?.last_tool && (
            <Text style={styles.label}>Last Tool: <Text style={{ color: '#007BFF' }}>{state.data.last_tool}</Text></Text>
        )}

        <View style={styles.codeBlock}>
           <Text style={styles.codeText}>// World State</Text>
           <Text style={styles.codeText}>{JSON.stringify(state?.data?.state || {}, null, 2)}</Text>
           <Text style={styles.codeText}>{"\n"}// Shared Registry</Text>
           <Text style={styles.codeText}>{JSON.stringify(state?.data?.shared_state || {}, null, 2)}</Text>
        </View>
        </View>
      </ScrollView>
    </View>
  );

}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  headerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff' },
  reloadBtn: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#1A1A1A', paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: '#333' },
  reloadText: { color: '#007BFF', marginLeft: 8, fontWeight: '600' },
  searchBar: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#222', borderRadius: 10, paddingHorizontal: 15, marginBottom: 16, height: 40, borderWidth: 1, borderColor: '#333' },
  searchInput: { flex: 1, color: '#FFF', height: 40, fontSize: 14 },
  card: { backgroundColor: '#222', padding: 24, borderRadius: 12, borderWidth: 1, borderColor: '#333' },
  title: { fontSize: 22, fontWeight: '600', color: '#fff' },
  text: { color: '#AAA', fontSize: 16, marginBottom: 16 },
  label: { color: '#888', fontSize: 13, marginBottom: 4, fontWeight: '500' },
  codeBlock: { backgroundColor: '#000', padding: 16, borderRadius: 8, marginTop: 10 },
  codeText: { color: '#00FF41', fontFamily: 'monospace', fontSize: 14 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' }
});

