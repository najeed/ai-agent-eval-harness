# Industrial Stability: Singleton Process Guard

AgentV ensures deterministic, isolated evaluations through a strict **Singleton Process Guard**. This is critical for industrial pipelines where conflicting agent runs or stale processes can corrupt audit trails.

---

## 1. The Singleton Guard logic

The engine maintains a PID-based locking mechanism to prevent multiple orchestration instances from interfering with the same industrial environment.

### PID-Based Locking
- **Lock File**: `.aes/lock/server.pid`
- **Behavior**: If a process attempts to start while a lock is held, the engine verifies if the PID is active. If active, it exits with `LOCK_ERROR`.

---

## 2. Stale Process Remediation

Using the `psutil` library, AgentV automatically detects and cleans up "ghost processes" from crashed or interrupted runs.

### Remediation Protocol
1. **Detection**: Identifying stale pids in the `.aes/lock/` directory.
2. **Cleanup**: Sending `SIGTERM` (and `SIGKILL` if necessary) to child processes to free up port 5000 and the VFS workspace.
3. **Recovery**: Releasing the PID lock to allow a fresh evaluation to proceed.

---

## 3. Engineering Constraints

- **Single Host Isolation**: The guard prevents horizontal collision on a single VM.
- **VFS Locking**: In addition to PID locks, the engine uses file-exclusive locks on the **Vertical Filesystem (VFS)** to protect simulation state.
