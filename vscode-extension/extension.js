const vscode = require('vscode');
const { exec } = require('child_process');

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
	console.log('MultiAgentEval is now active!');

	let runScenario = vscode.commands.registerCommand('eval-harness.runScenario', function () {
		const activeEditor = vscode.window.activeTextEditor;
		if (activeEditor && activeEditor.document.fileName.endsWith('.json')) {
			const filePath = activeEditor.document.fileName;
			vscode.window.showInformationMessage(`Running Eval Trace for: ${filePath}`);
			
			// Simulate running the CLI
			exec(`eval-harness evaluate --path ${filePath}`, (error, stdout, stderr) => {
				if (error) {
					vscode.window.showErrorMessage(`Eval Failed: ${stderr}`);
					return;
				}
				vscode.window.showInformationMessage('Eval Complete! View results in Admin Console.');
			});
		} else {
			vscode.window.showErrorMessage('Please open an AES Scenario JSON file first.');
		}
	});

	let openConsole = vscode.commands.registerCommand('eval-harness.openConsole', function () {
		vscode.env.openExternal(vscode.Uri.parse('http://localhost:5000'));
	});

	context.subscriptions.push(runScenario, openConsole);
}

function deactivate() {}

module.exports = {
	activate,
	deactivate
}
