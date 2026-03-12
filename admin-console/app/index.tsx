import { View, Text, StyleSheet, TextInput, TouchableOpacity } from 'react-native';
import { useState } from 'react';
import { Search, FileText, BarChart2, Activity, Book, Home } from 'lucide-react-native';
import { router } from 'expo-router';

export default function Dashboard() {
  const [search, setSearch] = useState('');
  const statusItems = [
    { label: 'Agent Endpoint', value: 'Connected' },
    { label: 'Engine Version', value: 'v1.0.0' },
    { label: 'Control Plane', value: 'Active' },
    { label: 'Telemetry', value: 'Online' },
  ];

  const filteredItems = statusItems.filter(item => 
    item.label.toLowerCase().includes(search.toLowerCase()) || 
    item.value.toLowerCase().includes(search.toLowerCase())
  );

  const menuItems = [
    { id: 'scenarios', title: 'Scenarios', path: '/scenarios', icon: FileText },
    { id: 'reports', title: 'Reports & Traces', path: '/reports', icon: BarChart2 },
    { id: 'debugger', title: 'Visual Debugger', path: '/debugger', icon: Activity },
    { id: 'docs', title: 'Documentation', path: '/docs', icon: Book },
    { id: 'editor', title: 'Visual AES Builder', path: '/editor', icon: FileText },
  ];

  const filteredMenu = menuItems.filter(item => 
    item.title.toLowerCase().includes(search.toLowerCase())
  );
  return (
    <View style={styles.container}>
      <Text style={styles.header}>Admin Console</Text>
      
      <View style={styles.searchSection}>
        <Search color="#AAA" size={20} style={{ marginRight: 10 }} />
        <TextInput
          style={styles.searchInput}
          placeholder="Search dashboard..."
          placeholderTextColor="#666"
          value={search}
          onChangeText={setSearch}
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.title}>System Status</Text>
        {filteredItems.map((item, idx) => (
           <Text key={idx} style={styles.text}>{item.label}: <Text style={{ color: '#007BFF' }}>{item.value}</Text></Text>
        ))}
        {filteredItems.length === 0 && <Text style={styles.text}>No matching status found.</Text>}
      </View>

      <View style={[styles.card, { marginTop: 20 }]}>
        <Text style={styles.title}>Quick Access</Text>
        <View style={styles.menuGrid}>
          {filteredMenu.map((item) => {
            const Icon = item.icon;
            return (
              <TouchableOpacity 
                key={item.id} 
                style={styles.menuItem}
                onPress={() => router.push(item.path)}
              >
                <Icon color="#007BFF" size={24} />
                <Text style={styles.menuText}>{item.title}</Text>
              </TouchableOpacity>
            );
          })}
          {filteredMenu.length === 0 && <Text style={styles.text}>No matching menu options found.</Text>}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    backgroundColor: '#111',
  },
  header: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 20,
    fontFamily: 'Inter',
  },
  searchSection: { 
    flexDirection: 'row', 
    alignItems: 'center', 
    backgroundColor: '#222', 
    borderRadius: 12, 
    paddingHorizontal: 15, 
    marginBottom: 20, 
    borderWidth: 1, 
    borderColor: '#333' 
  },
  searchInput: { 
    flex: 1, 
    color: '#FFF', 
    height: 45, 
    fontSize: 16 
  },
  card: {
    backgroundColor: '#222',
    padding: 20,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#333',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2,
    shadowRadius: 10,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#007BFF',
    marginBottom: 10,
  },
  text: {
    color: '#AAA',
    fontSize: 14,
    marginBottom: 4,
  },
  menuGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },
  menuItem: {
    width: '48%',
    backgroundColor: '#1A1A1A',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#333',
  },
  menuText: {
    color: '#FFF',
    marginTop: 8,
    fontSize: 12,
    fontWeight: '600',
    textAlign: 'center',
  }
});
