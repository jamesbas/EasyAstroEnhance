import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface State {
  error: Error | null;
}

// Last line of defence: an unexpected rendering error shows a message and a reload button instead of an empty page.
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('EasyAstroEnhance display error', error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash" role="alert" data-testid="app-error">
        <h1>Something went wrong in the page</h1>
        <p>Your images and results are safe; nothing was lost. Reload the page to continue.</p>
        <p className="muted small">{this.state.error.message}</p>
        <button type="button" className="btn primary" onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}
