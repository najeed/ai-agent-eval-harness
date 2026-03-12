import { View, Text, StyleSheet, FlatList, ActivityIndicator, TouchableOpacity, TextInput, ScrollView } from 'react-native';
import { useEffect, useState } from 'react';
import { FileText, Search, Filter, CheckCircle, AlertTriangle, XCircle } from 'lucide-react-native';

export default function Scenarios() {
  const [scenarios, setScenarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [industry, setIndustry] = useState('');
  const [difficulty, setDifficulty] = useState('');

  const industries = ['All', 'Telecom', 'Finance', 'Health', 'Retail'];
  const difficulties = ['Any', '1', '2', '3', '4', '5'];

  const fetchScenarios = () => {
    setLoading(true);
    let url = `http://127.0.0.1:5000/api/scenarios?`;
    if (query) url += `q=${encodeURIComponent(query)}&`;
    if (industry && industry !== 'All') url += `industry=${encodeURIComponent(industry.toLowerCase())}&`;
    if (difficulty && difficulty !== 'Any') url += `difficulty=${difficulty}&`;

    fetch(url)
      .then(res => res.json())
      .then(data => {
        setScenarios(data.scenarios || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load scenarios', err);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchScenarios();
  }, [industry, difficulty]);

  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      fetchScenarios();
    }, 300);

    return () => clearTimeout(delayDebounceFn);
  }, [query]);

  const handleRun = (path: string) => {
    fetch('http://127.0.0.1:5000/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    }).then(res => res.json()).then(data => alert(data.message));
  };

  const getStatusIcon = (status: string) => {
    if (status === 'pass') return <CheckCircle color="#28A745" size={16} />;
    if (status === 'warning') return <AlertTriangle color="#FFC107" size={16} />;
    return <XCircle color="#DC3545" size={16} />;
  };

  return (
    <View style={styles.container}>
      <Text style={styles.header}>Scenario Explorer</Text>
      
      {/* Search Bar */}
      <View style={styles.searchSection}>
        <Search color="#AAA" size={20} style={{ marginRight: 10 }} />
        <TextInput
          style={styles.searchInput}
          placeholder="Search scenarios..."
          placeholderTextColor="#666"
          value={query}
          onChangeText={setQuery}
        />
      </View>

      {/* Industry Filters */}
      <View style={styles.filterSection}>
        <Text style={styles.filterLabel}>Industry:</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          {industries.map(ind => (
            <TouchableOpacity 
              key={ind} 
              style={[styles.chip, industry === ind && styles.activeChip]} 
              onPress={() => setIndustry(ind)}
            >
              <Text style={[styles.chipText, industry === ind && styles.activeChipText]}>{ind}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      {loading ? (
        <View style={styles.loaderContainer}>
          <ActivityIndicator size="large" color="#007BFF" />
        </View>
      ) : (
        <FlatList
          data={scenarios}
          keyExtractor={item => item.id || item.scenario_id}
          renderItem={({ item }) => (
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                  <FileText color="#17A2B8" size={24} style={{ marginRight: 10 }} />
                  <Text style={styles.title} numberOfLines={1}>{item.title || 'Untitled Scenario'}</Text>
                </View>
                <View style={styles.badge}>
                  {getStatusIcon(item.status)}
                  <Text style={styles.badgeText}>{item.lint_score ?? 0}%</Text>
                </View>
              </View>
              
              <View style={styles.metaRow}>
                <Text style={styles.text}>ID: {item.id || item.scenario_id}</Text>
                <Text style={styles.diffText}>Diff: {item.difficulty || '1'}</Text>
              </View>
              <Text style={styles.text}>Industry: <Text style={{ color: '#FFF' }}>{item.industry}</Text></Text>
              
              <TouchableOpacity style={styles.button} onPress={() => handleRun(item.path || item.file_path)}>
                <Text style={styles.buttonText}>Run Evaluation</Text>
              </TouchableOpacity>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff', marginBottom: 20 },
  searchSection: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#222', borderRadius: 12, paddingHorizontal: 15, marginBottom: 16, borderWidth: 1, borderColor: '#333' },
  searchInput: { flex: 1, color: '#FFF', height: 45, fontSize: 16 },
  filterSection: { marginBottom: 20 },
  filterLabel: { color: '#AAA', fontSize: 14, marginBottom: 8, fontWeight: '600' },
  chip: { paddingHorizontal: 16, paddingVertical: 6, borderRadius: 20, backgroundColor: '#222', marginRight: 8, borderWidth: 1, borderColor: '#444' },
  activeChip: { backgroundColor: '#007BFF', borderColor: '#007BFF' },
  chipText: { color: '#AAA', fontSize: 13 },
  activeChipText: { color: '#FFF', fontWeight: 'bold' },
  card: { backgroundColor: '#1A1A1A', padding: 20, borderRadius: 12, marginBottom: 16, borderWidth: 1, borderColor: '#333' },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  title: { fontSize: 18, fontWeight: '600', color: '#fff', flex: 1 },
  badge: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#333', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  badgeText: { color: '#FFF', fontSize: 12, marginLeft: 4, fontWeight: '700' },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  text: { color: '#AAA', fontSize: 14 },
  diffText: { color: '#FFC107', fontSize: 14, fontWeight: 'bold' },
  button: { marginTop: 16, backgroundColor: '#007BFF', padding: 12, borderRadius: 8, alignItems: 'center' },
  buttonText: { color: '#fff', fontWeight: 'bold', fontSize: 15 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' }
});
