import { useLocalSearchParams, Stack } from 'expo-router';
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { WebView } from 'react-native-webview';

/**
 * Universal Plugin Screen
 * Supports Mode A (Native SDUI) and Mode B (Secure WebView)
 */
export default function PluginScreen() {
  const { id, path, token, title } = useLocalSearchParams();
  const [loading, setLoading] = useState(true);
  const [pluginData, setPluginData] = useState<any>(null);
  const [mode, setMode] = useState<'SDUI' | 'WEB' | null>(null);

  useEffect(() => {
    // Attempt to fetch content from the backend to determine rendering mode
    const pluginUrl = `http://127.0.0.1:5000${path}?token=${token}`;
    
    fetch(pluginUrl)
      .then(async res => {
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          const data = await res.json();
          setPluginData(data);
          setMode('SDUI');
        } else {
          setMode('WEB');
        }
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load plugin content', err);
        setMode('WEB'); // Fallback to WebView
        setLoading(false);
      });
  }, [id, path, token]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#007BFF" />
        <Text style={styles.text}>Loading Plugin...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: (title as string) || 'Plugin' }} />
      
      {mode === 'SDUI' ? (
        <View style={styles.nativeContainer}>
          <Text style={styles.header}>{pluginData?.title || 'Plugin View'}</Text>
          {/* Simple native list renderer for Mode A (SDUI) */}
          {pluginData?.items?.map((item: any, index: number) => (
            <View key={index} style={styles.card}>
              <Text style={styles.cardTitle}>{item.label}</Text>
              <Text style={styles.cardValue}>{item.value}</Text>
            </View>
          ))}
          {!pluginData?.items && (
             <Text style={styles.text}>Native data-driven view (Mode A) successfully loaded but no data items found.</Text>
          )}
        </View>
      ) : (
        <WebView 
          source={{ 
            uri: `http://127.0.0.1:5000${path}?token=${token}`,
            headers: { 'X-Handoff-Token': token as string }
          }} 
          style={{ flex: 1 }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#111',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#111',
  },
  nativeContainer: {
    padding: 20,
  },
  header: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 20,
  },
  text: {
    color: '#AAA',
    marginTop: 10,
  },
  card: {
    backgroundColor: '#222',
    padding: 15,
    borderRadius: 8,
    marginBottom: 10,
    borderLeftWidth: 4,
    borderLeftColor: '#007BFF',
  },
  cardTitle: {
    color: '#AAA',
    fontSize: 12,
    textTransform: 'uppercase',
  },
  cardValue: {
    color: '#FFF',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 4,
  }
});
