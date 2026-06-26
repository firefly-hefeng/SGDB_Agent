import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}
interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the console.error only in dev; production should report to a service.
    if (import.meta.env.DEV) {
      console.error('ErrorBoundary:', error, info);
    }
  }

  private reset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div
          role="alert"
          className="flex items-center justify-center h-screen bg-canvas-subtle"
        >
          <div className="text-center space-y-4 max-w-md px-6">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-amber-100 mb-2">
              <AlertTriangle size={22} className="text-amber-700" />
            </div>
            <h1 className="text-lg font-semibold text-ink">Something went wrong</h1>
            <p className="text-sm text-ink-muted">
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <details className="text-2xs text-ink-subtle">
              <summary className="cursor-pointer text-ink-muted hover:text-ink">
                Technical details
              </summary>
              <pre className="mt-2 p-2 bg-canvas border border-line rounded text-left overflow-x-auto">
                {this.state.error?.stack?.split('\n').slice(0, 6).join('\n')}
              </pre>
            </details>
            <div className="flex items-center justify-center gap-2 pt-2">
              <button
                onClick={() => {
                  this.reset();
                  window.location.reload();
                }}
                className="btn btn-accent text-sm"
              >
                <RefreshCw size={14} /> Reload
              </button>
              <a href="/singligent/" className="btn btn-secondary text-sm">
                <Home size={14} /> Home
              </a>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
