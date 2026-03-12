import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export default function ScenarioEditor() {
  const [scenario, setScenario] = useState({
    scenario_id: 'new_scenario',
    title: 'Untitled Scenario',
    industry: 'generic',
    tasks: [{ id: '1', description: 'Sample task' }],
  });
  const [taskSearch, setTaskSearch] = useState('');

  const saveScenario = () => {
    fetch('http://127.0.0.1:5000/api/scenarios', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scenario)
    })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        Alert.alert('Success', `Scenario saved to: ${data.path}`);
      } else {
        Alert.alert('Error', data.error || 'Failed to save scenario');
      }
    })
    .catch(err => Alert.alert('Error', 'Connection failed: ' + err.message));
  };


  const addTask = () => {
    setScenario({
      ...scenario,
      tasks: [...scenario.tasks, { id: String(Date.now()), description: '' }],
    });
  };

  const moveTask = (index: number, direction: 'up' | 'down') => {
    const newTasks = [...scenario.tasks];
    const newIndex = direction === 'up' ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= newTasks.length) return;
    [newTasks[index], newTasks[newIndex]] = [newTasks[newIndex], newTasks[index]];
    setScenario({ ...scenario, tasks: newTasks });
  };

  const deleteTask = (index: number) => {
    const newTasks = scenario.tasks.filter((_, i) => i !== index);
    setScenario({ ...scenario, tasks: newTasks });
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Visual AES Builder</Text>
        <Text style={styles.subtitle}>Construct agentic evaluation logic visually</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Scenario ID</Text>
        <TextInput
          style={styles.input}
          value={scenario.scenario_id}
          onChangeText={(text: string) => setScenario({ ...scenario, scenario_id: text })}
        />

        <Text style={styles.label}>Title</Text>
        <TextInput
          style={styles.input}
          value={scenario.title}
          onChangeText={(text: string) => setScenario({ ...scenario, title: text })}
        />

        <Text style={styles.label}>Tasks (State Nodes)</Text>
        <View style={styles.searchBar}>
          <Ionicons name="search" size={18} color="#9CA3AF" />
          <TextInput
            style={styles.searchInnerInput}
            placeholder="Filter tasks..."
            value={taskSearch}
            onChangeText={setTaskSearch}
          />
        </View>

        {scenario.tasks
          .map((task: any, index: number) => ({ ...task, originalIndex: index }))
          .filter((task: any) => task.description.toLowerCase().includes(taskSearch.toLowerCase()))
          .map((task: any) => {
            const index = task.originalIndex;
            return (
              <View key={task.id} style={styles.taskItem}>
                <View style={styles.taskActions}>
                   <TouchableOpacity onPress={() => moveTask(index, 'up')} disabled={index === 0}>
                      <Ionicons name="arrow-up-circle" size={20} color={index === 0 ? "#E5E7EB" : "#007AFF"} />
                   </TouchableOpacity>
                   <TouchableOpacity onPress={() => moveTask(index, 'down')} disabled={index === scenario.tasks.length - 1}>
                      <Ionicons name="arrow-down-circle" size={20} color={index === scenario.tasks.length - 1 ? "#E5E7EB" : "#007AFF"} />
                   </TouchableOpacity>
                </View>
                <Text style={styles.taskNumber}>{index + 1}</Text>
                <TextInput
                  style={[styles.input, { flex: 1, marginBottom: 0 }]}
                  placeholder="Describe task expectation..."
                  value={task.description}
                  onChangeText={(text: string) => {
                    const newTasks = [...scenario.tasks];
                    newTasks[index].description = text;
                    setScenario({ ...scenario, tasks: newTasks });
                  }}
                />
                <TouchableOpacity onPress={() => deleteTask(index)} style={{ marginLeft: 8 }}>
                   <Ionicons name="trash-outline" size={20} color="#EF4444" />
                </TouchableOpacity>
              </View>
            );
          })}

        <TouchableOpacity style={styles.addButton} onPress={addTask}>
          <Ionicons name="add-circle" size={24} color="#007AFF" />
          <Text style={styles.addButtonText}>Add Task Node</Text>
        </TouchableOpacity>
      </View>

      <TouchableOpacity style={styles.saveButton} onPress={saveScenario}>
        <Text style={styles.saveButtonText}>Generate AES JSON</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
    padding: 20,
  },
  header: {
    marginBottom: 30,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#111827',
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    marginTop: 4,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 3,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 8,
    marginTop: 16,
  },
  input: {
    backgroundColor: '#F3F4F6',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    color: '#111827',
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  taskItem: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  taskActions: {
    marginRight: 8,
    flexDirection: 'column',
    justifyContent: 'center',
  },
  taskNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#007AFF',
    color: '#FFFFFF',
    textAlign: 'center',
    lineHeight: 28,
    marginRight: 10,
    fontWeight: 'bold',
  },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 20,
    padding: 12,
    borderWidth: 1,
    borderColor: '#007AFF',
    borderStyle: 'dashed',
    borderRadius: 8,
    justifyContent: 'center',
  },
  addButtonText: {
    marginLeft: 8,
    color: '#007AFF',
    fontWeight: '600',
  },
  searchBar: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    borderRadius: 8,
    paddingHorizontal: 10,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  searchInnerInput: {
    flex: 1,
    height: 40,
    fontSize: 14,
    marginLeft: 5,
  },
  saveButton: {
    backgroundColor: '#111827',
    borderRadius: 12,
    padding: 18,
    alignItems: 'center',
    marginTop: 30,
    marginBottom: 40,
  },
  saveButtonText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
});
