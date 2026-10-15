import React from 'react';
import {
  Activity,
  BarChart2,
  Bell,
  BookOpen,
  Box,
  CheckCircle2,
  ClipboardCheck,
  Compass,
  Cpu,
  Database,
  FileCheck,
  FileText,
  GitBranch,
  HeartPulse,
  Home,
  Layers,
  Lock,
  Play,
  Radio,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Terminal,
  TrendingUp,
  Users,
  Zap,
  CircleHelp,
  type LucideIcon,
} from 'lucide-react';

/** Normalize kebab-case, snake_case, camelCase, and spaced signed names. */
export function normalizeNavigationIconName(value: string): string {
  return value.replace(/([a-z0-9])([A-Z])/g, '$1-$2').replace(/[\s_]+/g, '-').toLowerCase();
}

const ICONS: Readonly<Record<string, LucideIcon>> = {
  activity: Activity,
  'bar-chart': BarChart2,
  bell: Bell,
  'book-open': BookOpen,
  box: Box,
  'check-circle': CheckCircle2,
  'clipboard-check': ClipboardCheck,
  compass: Compass,
  cpu: Cpu,
  database: Database,
  'file-check': FileCheck,
  'file-text': FileText,
  'git-branch': GitBranch,
  'heart-pulse': HeartPulse,
  home: Home,
  layers: Layers,
  lock: Lock,
  play: Play,
  radio: Radio,
  server: Server,
  settings: Settings,
  shield: Shield,
  'shield-check': ShieldCheck,
  sparkles: Sparkles,
  terminal: Terminal,
  'trending-up': TrendingUp,
  users: Users,
  zap: Zap,
};

export const SUPPORTED_NAVIGATION_ICON_NAMES = Object.freeze(Object.keys(ICONS));

/** Resolve only the signed, allowlisted Lucide vocabulary. */
export function resolveNavigationIcon(icon: string | React.ReactNode | undefined): React.ReactNode {
  if (React.isValidElement(icon)) return icon;
  if (typeof icon === 'string') {
    const normalized = normalizeNavigationIconName(icon);
    const Icon = ICONS[normalized];
    if (Icon) return <Icon className="w-4 h-4" />;
    if ((import.meta as ImportMeta & { env?: { DEV?: boolean } }).env?.DEV) {
      console.warn(`[Console] Unknown signed navigation icon '${icon}'; using neutral fallback.`);
    }
  }
  return <CircleHelp className="w-4 h-4" />;
}
