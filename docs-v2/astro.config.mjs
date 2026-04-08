// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://najeed.github.io',
	base: '/ai-agent-eval-harness/v2',
	integrations: [
		starlight({
			title: 'MultiAgentEval',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/najeed/ai-agent-eval-harness' }
			],
			sidebar: [
				{
					label: 'Industry Evaluator',
					autogenerate: { directory: 'evaluator' },
				},
				{
					label: 'Agent Integrator',
					autogenerate: { directory: 'integrator' },
				},
				{
					label: 'Platform Extender',
					autogenerate: { directory: 'extender' },
				},
				{
					label: 'OSS Core Builder',
					autogenerate: { directory: 'builder' },
				},
				{
					label: 'Security Auditor',
					autogenerate: { directory: 'auditor' },
				},
			],
			customCss: [
				// Relative path to your custom CSS file
				'./src/assets/custom.css',
			],
		}),
	],
});
