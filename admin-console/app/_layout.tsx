import { Drawer } from 'expo-router/drawer';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, View, StyleSheet, Linking } from 'react-native';
import { 
  DrawerContentScrollView, 
  DrawerItemList, 
  DrawerItem 
} from '@react-navigation/drawer';
import { Home, FileText, BarChart2, Activity, Book, Github, Shield, Box, ExternalLink } from 'lucide-react-native';

const ICON_MAP: Record<string, any> = {
  'home': Home,
  'file-text': FileText,
  'bar-chart-2': BarChart2,
  'activity': Activity,
  'book': Book,
  'github': Github,
  'shield': Shield,
  'box': Box,
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

  function CustomDrawerContent(props: any) {
    return (
      <DrawerContentScrollView {...props}>
        {/* Render internal screens managed by Expo Router */}
        <DrawerItemList {...props} />
        
        {/* Render Dynamic / External / Plugin links */}
        {navItems.filter(item => item.type !== 'internal').map((item) => {
          const Icon = ICON_MAP[item.icon] || ExternalLink;
          return (
            <DrawerItem
              key={item.id}
              label={item.title}
              inactiveTintColor="#AAA"
              icon={({ color, size }) => <Icon color={color} size={size} />}
              onPress={async () => {
                if (item.type === 'external') {
                  Linking.openURL(item.path);
                } else if (item.type === 'plugin') {
                  // Secure Handoff: Get token before navigating
                  try {
                    const res = await fetch('http://127.0.0.1:5000/api/auth/handoff');
                    const { token } = await res.json();
                    router.push({
                      pathname: `/plugin/${item.id}`,
                      params: { path: item.path, token, title: item.title }
                    });
                  } catch (err) {
                    console.error('Handoff failed', err);
                  }
                }
              }}
            />
          );
        })}
      </DrawerContentScrollView>
    );
  }

  return (
    <Drawer 
      drawerContent={(props) => <CustomDrawerContent {...props} />}
      screenOptions={{ 
        headerStyle: { backgroundColor: '#1A1A1A' }, 
        headerTintColor: '#fff',
        drawerStyle: { backgroundColor: '#222' },
        drawerActiveTintColor: '#007BFF',
        drawerInactiveTintColor: '#AAA',
      }}
    >
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
      {/* Hide community from internal list as it is handled by custom drawer item */}
      <Drawer.Screen
        name="community"
        options={{
          drawerItemStyle: { display: 'none' }
        }}
      />
      {/* Dynamic Plugin Route */}
      <Drawer.Screen
        name="plugin/[id]"
        options={{
          drawerItemStyle: { display: 'none' },
          title: 'Plugin'
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
