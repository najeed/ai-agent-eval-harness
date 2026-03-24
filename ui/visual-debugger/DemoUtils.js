// --- Demo Logic Abstraction ---

export const useDemoHelper = (setTerminalOutput, setLatestRunId, setVerifiedRunId, setStep) => {
    const runCommand = async (command) => {
        try {
            const res = await fetch('/api/demo/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command })
            });
            const data = await res.json();
            if (data.error) {
                setTerminalOutput(prev => [...prev, { text: `Error: ${data.details || data.error}`, type: 'error' }]);
                return null;
            }
            return data;
        } catch (err) {
            setTerminalOutput(prev => [...prev, { text: `Fetch Error: ${err.message}`, type: 'error' }]);
            return null;
        }
    };

    const runEval = async (scenarioPath, agentUrl) => {
        setTerminalOutput([{ text: `Executing Evaluation Suite: ${scenarioPath}...`, type: "system" }]);
        const data = await runCommand(`multiagent-eval evaluate --path ${scenarioPath} --agent ${agentUrl}`);
        if (data) {
            setTerminalOutput(prev => [...prev, ...data.stdout.split('\n').map(l => ({ text: l, type: 'info' }))]);
            const match = data.stdout.match(/Run ID:\s*([^\s\n]+)/);
            if (match) {
                setLatestRunId(match[1]);
            } else {
                const runRes = await fetch('/api/runs');
                const runData = await runRes.json();
                if (runData.runs && runData.runs.length > 0) {
                    setLatestRunId(runData.runs[0].run_id);
                }
            }
            return true;
        }
        return false;
    };

    const runTriage = async (runId) => {
        setTerminalOutput([{ text: `Isolating Root Cause for ${runId}...`, type: "system" }]);
        const data = await runCommand(`multiagent-eval triage --run-id ${runId}`);
        if (data) {
            setTerminalOutput(prev => [...prev, ...data.stdout.split('\n').map(l => ({ text: l, type: 'info' }))]);
            return true;
        }
        return false;
    };

    const runFix = async (source, target, scenarioPath, agentUrl) => {
        setTerminalOutput([{ text: "Applying Strategic Patch...", type: "system" }]);
        const patchRes = await runCommand(`copy ${source} ${target}`);
        if (patchRes) {
            setTerminalOutput(prev => [...prev, { text: "Patch applied successfully. Verifying fix...", type: "info" }]);
            const verifyData = await runCommand(`multiagent-eval evaluate --path ${scenarioPath} --agent ${agentUrl}`);
            if (verifyData) {
                setTerminalOutput(prev => [...prev, ...verifyData.stdout.split('\n').map(l => ({ text: l, type: 'info' }))]);
                const match = verifyData.stdout.match(/Run ID:\s*([^\s\n]+)/);
                if (match) {
                    setVerifiedRunId(match[1]);
                }
                return true;
            }
        }
        return false;
    };

    return {
        runCommand,
        runEval,
        runTriage,
        runFix
    };
};
