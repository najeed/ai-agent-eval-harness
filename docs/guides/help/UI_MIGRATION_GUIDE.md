# UI Migration Guide: Admin Console to Visual Debugger

This guide assists plugin developers in transitioning custom visual components from the legacy **Admin Console** (React Native) to the new **Integrated Visual Suite** (React).

## 1. Architectural Shift

The new suite is built on **React (Web)** and integrated directly into the `eval_runner` via a Flask-based API bridge. This eliminates the need for Expo/React Native dependencies and provides a true "Zero-Touch" experience.

| Feature | Legacy Admin Console | New Visual Debugger |
| :--- | :--- | :--- |
| **Framework** | React Native (Expo) | React (Web) |
| **State Propagation** | WebSocket / Local JSON | HTTP POST / Live Bridge Plugin |
| **Styling** | StyleSheet (RN) | Tailwind CSS & Vanilla CSS |
| **Extensibility** | Manual build changes | `on_register_console_routes` hook |

## 2. Component Mapping

If you have custom components, follow this mapping to port them:

| RN Component | React Web Equivalent |
| :--- | :--- |
| `<View>` | `<div>` |
| `<Text>` | `<span>` or `<p>` |
| `<ScrollView>` | `div { overflow-y: auto }` |
| `<TouchableOpacity>` | `<button>` |
| `StyleSheet.create` | Tailwind classes or CSS Modules |

## 3. Registering Custom Views

To add a custom view to the new console, use the `on_register_console_routes` lifecycle hook in your plugin.

### Legacy (Static Registration)
In the old console, you had to modify `App.js` or `navigation/`.

### New (Plugin-Driven)
```python
from flask import Blueprint
from eval_runner.plugins import BaseEvalPlugin

class MyPlugin(BaseEvalPlugin):
    def on_register_console_routes(self, app, nav_registry):
        # 1. Register a navigation link
        nav_registry.append({
            "id": "my-plugin-view",
            "title": "Custom Data",
            "path": "/plugin/my-data",
            "icon": "box",
            "type": "internal"
        })
        
        # 2. Register a Flask Blueprint for your data
        bp = Blueprint("my_plugin", __name__, url_prefix="/api/plugin")
        @bp.route("/my-data")
        def get_data():
            return {"status": "ok", "data": "..."}
            
        app.register_blueprint(bp)
```

## 4. Hooking into the Live Bridge

The new `RemoteBridgePlugin` automatically propagates core events to the console. If your custom view needs specific engine data, subscribe to the `EventEmitter` in your backend route or poll the `/api/debugger/state` endpoint.

### Real-time Event Subscription
```python
from eval_runner.events import EventEmitter

def my_callback(event):
    if event.name == "my_custom_event":
        # Store for the UI to pick up
        pass

EventEmitter.subscribe(my_callback)
```

## 5. UI Implementation (Frontend)

The new frontend is located in `ui/visual-debugger/App.jsx`. It's a single-component React application (for now) to ensure Zero-Touch portability.

- **To add a tab**: Add a case to the `renderContent` switch in `App.jsx`.
- **To add an icon**: Add an entry to the `icons` object at the top of `App.jsx`.

---

> [!IMPORTANT]
> The React Native `admin-console/` has been officially **REMOVED** as of v1.2. All users must migrate to the Integrated Visual Suite. This guide remains for reference for those still porting custom plugin views.
