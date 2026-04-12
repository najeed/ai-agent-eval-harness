// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const base = process.env.BASE_URL || '/ai-agent-eval-harness/';

/**
 * Remark plugin to prepend the base path to internal absolute-style links.
 */
function remarkReplaceBase() {
	const cleanBase = base.replace(/\/$/, '');
	/**
	 * @param {import('mdast').Root} tree
	 */
	return (tree) => {
		/**
		 * @param {import('mdast').Content | import('mdast').Root} node
		 */
		function visit(node) {
			if (node.type === 'link' || node.type === 'image') {
				// @ts-ignore - url exists on link/image but not all Content types
				if (node.url && node.url.startsWith('/') && !node.url.startsWith('//') && !node.url.startsWith(cleanBase + '/')) {
					// @ts-ignore
					node.url = cleanBase + node.url;
				}
			}
			if ('children' in node && Array.isArray(node.children)) {
				node.children.forEach(visit);
			}
		}
		visit(tree);
	};
}

// https://astro.build/config
export default defineConfig({
	site: 'https://najeed.github.io',
	base,
	markdown: {
		remarkPlugins: [remarkReplaceBase],
	},
	integrations: [
		starlight({
			title: 'AgentV',
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
