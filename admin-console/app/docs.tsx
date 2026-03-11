import { View, Text, StyleSheet, FlatList, ActivityIndicator, TouchableOpacity, ScrollView } from 'react-native';
import { useEffect, useState } from 'react';
import { BookOpen, ArrowLeft } from 'lucide-react-native';
import Markdown from 'react-native-markdown-display';

export default function Docs() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // State for reading a specific document
  const [selectedDoc, setSelectedDoc] = useState<{id: string, title: string} | null>(null);
  const [docContent, setDocContent] = useState<string>('');
  const [contentLoading, setContentLoading] = useState(false);

  useEffect(() => {
    fetch('http://127.0.0.1:5000/api/docs')
      .then(res => res.json())
      .then(data => {
        setDocs(data.docs || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load docs list', err);
        setLoading(false);
      });
  }, []);

  const loadDocument = (doc: any) => {
    setSelectedDoc(doc);
    setContentLoading(true);
    fetch(`http://127.0.0.1:5000/api/docs/${encodeURIComponent(doc.id)}`)
      .then(res => res.json())
      .then(data => {
        setDocContent(data.content || 'No content found.');
        setContentLoading(false);
      })
      .catch(err => {
        console.error('Failed to load document content', err);
        setDocContent('Error loading document.');
        setContentLoading(false);
      });
  };

  if (loading) {
    return (
      <View style={styles.loaderContainer}>
        <ActivityIndicator size="large" color="#007BFF" />
      </View>
    );
  }

  // --- READER VIEW ---
  if (selectedDoc) {
    return (
      <View style={styles.container}>
        <TouchableOpacity style={styles.backButton} onPress={() => setSelectedDoc(null)}>
          <ArrowLeft color="#007BFF" size={24} style={{ marginRight: 8 }} />
          <Text style={styles.backButtonText}>Back to Library</Text>
        </TouchableOpacity>
        <Text style={styles.header}>{selectedDoc.title}</Text>
        
        {contentLoading ? (
           <ActivityIndicator size="large" color="#007BFF" style={{ marginTop: 40 }} />
        ) : (
           <ScrollView style={styles.markdownContainer}>
             <Markdown style={markdownStyles}>
                {docContent}
             </Markdown>
           </ScrollView>
        )}
      </View>
    );
  }

  // --- LIBRARY VIEW ---
  return (
    <View style={styles.container}>
      <Text style={styles.header}>Documentation Library</Text>
      <FlatList
        data={docs}
        keyExtractor={item => item.id}
        renderItem={({ item }) => (
          <TouchableOpacity style={styles.card} onPress={() => loadDocument(item)}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <BookOpen color="#17A2B8" size={24} style={{ marginRight: 16 }} />
              <View>
                <Text style={styles.title}>{item.title}</Text>
                <Text style={styles.text}>{item.id}</Text>
              </View>
            </View>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const markdownStyles = StyleSheet.create({
  body: { color: '#E0E0E0', fontSize: 16, lineHeight: 24, paddingBottom: 40 },
  heading1: { color: '#FFF', fontSize: 28, fontWeight: 'bold', marginTop: 16, marginBottom: 8 },
  heading2: { color: '#FFF', fontSize: 24, fontWeight: 'bold', marginTop: 16, marginBottom: 8 },
  heading3: { color: '#FFF', fontSize: 20, fontWeight: 'bold', marginTop: 16, marginBottom: 8 },
  code_inline: { backgroundColor: '#333', color: '#00FF41', padding: 4, borderRadius: 4, fontFamily: 'monospace' },
  code_block: { backgroundColor: '#000', color: '#00FF41', padding: 12, borderRadius: 8, fontFamily: 'monospace', marginVertical: 8 },
  link: { color: '#007BFF', textDecorationLine: 'none' },
  list_item: { marginTop: 4, marginBottom: 4 }
});

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: '#111' },
  header: { fontSize: 28, fontWeight: 'bold', color: '#fff', marginBottom: 20 },
  card: { backgroundColor: '#222', padding: 20, borderRadius: 12, marginBottom: 12, borderWidth: 1, borderColor: '#333' },
  title: { fontSize: 18, fontWeight: '600', color: '#fff' },
  text: { color: '#AAA', fontSize: 14, marginTop: 4 },
  loaderContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#111' },
  backButton: { flexDirection: 'row', alignItems: 'center', marginBottom: 16 },
  backButtonText: { color: '#007BFF', fontSize: 16, fontWeight: '600' },
  markdownContainer: { flex: 1, backgroundColor: '#1A1A1A', padding: 20, borderRadius: 12, borderWidth: 1, borderColor: '#333' }
});
