import { View, Text, StyleSheet } from 'react-native';

export default function Dashboard() {
  return (
    <View style={styles.container}>
      <Text style={styles.header}>Admin Console</Text>
      <View style={styles.card}>
        <Text style={styles.title}>System Status</Text>
        <Text style={styles.text}>Agent Endpoint: Connected</Text>
        <Text style={styles.text}>Engine Version: v1.0.0</Text>
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
  }
});
