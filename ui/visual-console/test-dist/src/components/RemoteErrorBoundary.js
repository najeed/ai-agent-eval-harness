import { jsx as _jsx } from "react/jsx-runtime";
import React from 'react';
// NodeNext-safe relative import (the docmodel test harness compiles this
// module for execution under plain node).
import { ExtensionLoadError } from './ExtensionLoadError.js';
/**
 * Failure isolation for dynamically mounted remote extension modules: a
 * throwing or unmountable child is contained here and replaced by the
 * contract-conforming ExtensionLoadError surface — never a blank screen and
 * never a crash of the host shell.
 */
export class RemoteErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false };
    }
    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }
    componentDidCatch(error, errorInfo) {
        console.error(`[MicroFrontend] Failed to load remote entry: ${this.props.entryUrl}`, error, errorInfo);
    }
    render() {
        if (this.state.hasError) {
            return (_jsx(ExtensionLoadError, { title: "Failed to Load Extension Module", entryUrl: this.props.entryUrl, message: this.state.error?.message || 'Module fetch or evaluation failed.' }));
        }
        return this.props.children;
    }
}
export default RemoteErrorBoundary;
