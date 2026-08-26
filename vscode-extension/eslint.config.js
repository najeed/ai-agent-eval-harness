// ESLint v10 flat config. The extension is CommonJS Node code; keep the
// rule surface minimal and equivalent to a default `eslint:recommended` run.
const js = require('@eslint/js');

module.exports = [
	{
		ignores: ['node_modules/**', 'aes.schema.json'],
	},
	js.configs.recommended,
	{
		files: ['extension.js', 'scripts/**/*.js', 'test/**/*.js', 'eslint.config.js'],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: 'commonjs',
			globals: {
				vscode: 'readonly',
				console: 'readonly',
				process: 'readonly',
				require: 'readonly',
				module: 'writable',
				exports: 'writable',
				__dirname: 'readonly',
			},
		},
		rules: {
			'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
		},
	},
];
