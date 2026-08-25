import React from 'react';
// NodeNext-safe relative import (the docmodel test harness compiles this
// module for execution under plain node).
import { ExtensionLoadError } from './ExtensionLoadError.js';

export interface RemoteErrorState {
  hasError: boolean;
  error?: Error;
}

/**
 * Failure isolation for dynamically mounted remote extension modules: a
 * throwing or unmountable child is contained here and replaced by the
 * contract-conforming ExtensionLoadError surface — never a blank screen and
 * never a crash of the host shell.
 */
export class RemoteErrorBoundary extends React.Component<
  { children: React.ReactNode; entryUrl: string },
  RemoteErrorState
> {
  constructor(props: { children: React.ReactNode; entryUrl: string }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): RemoteErrorState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[MicroFrontend] Failed to load remote entry: ${this.props.entryUrl}`, error, errorInfo);
  }

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <ExtensionLoadError
          title="Failed to Load Extension Module"
          entryUrl={this.props.entryUrl}
          message={this.state.error?.message || 'Module fetch or evaluation failed.'}
        />
      );
    }
    return this.props.children;
  }
}

export default RemoteErrorBoundary;
