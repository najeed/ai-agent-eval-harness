import { Drawer } from 'expo-router/drawer';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View, StyleSheet } from 'react-native';
import { Home, FileText, BarChart2, Activity, Book, Github } from 'lucide-react-native';

const ICON_MAP: Record<string, any> = {
  'home': Home,
  'file-text': FileText,
  'bar-chart-2': BarChart2,
  'activity': Activity,
  'book': Book,
  'github': Github, // Social media icon request
};

export default function Layout() {
  const [navItems, setNavItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('http://127.0.0.1:5000/api/nav')
      .then(res => res.json())
      .then(data => {
        setNavItems(data.nav || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('Failed to load navigation', err);
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
    <Drawer screenOptions={{ 
      headerStyle: { backgroundColor: '#1A1A1A' }, 
      headerTintColor: '#fff',
      drawerStyle: { backgroundColor: '#222' },
      drawerActiveTintColor: '#007BFF',
      drawerInactiveTintColor: '#AAA',
    }}>
      <Drawer.Screen
        name="index"
        options={{
          drawerLabel: 'Dashboard',
          title: 'Dashboard',
          drawerIcon: ({ color, size }) => <Home color={color} size={size} />
        }}
      />
      <Drawer.Screen
        name="scenarios"
        options={{
          drawerLabel: 'Scenarios',
          title: 'Scenarios',
          drawerIcon: ({ color, size }) => <FileText color={color} size={size} />
        }}
      />
      <Drawer.Screen
        name="reports"
        options={{
          drawerLabel: 'Reports & Traces',
          title: 'Reports & Traces',
          drawerIcon: ({ color, size }) => <BarChart2 color={color} size={size} />
        }}
      />
      <Drawer.Screen
        name="debugger"
        options={{
          drawerLabel: 'Visual Debugger',
          title: 'Visual Debugger',
          drawerIcon: ({ color, size }) => <Activity color={color} size={size} />
        }}
      />
      <Drawer.Screen
        name="docs"
        options={{
          drawerLabel: 'Documentation',
          title: 'Documentation',
          drawerIcon: ({ color, size }) => <Book color={color} size={size} />
        }}
      />
      <Drawer.Screen
        name="community"
        options={{
          drawerLabel: 'Community',
          title: 'Community',
          drawerIcon: ({ color, size }) => <Github color={color} size={size} />
        }}
      />
    </Drawer>
  );
}

const styles = StyleSheet.create({
  loaderContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#111',
  }
});
