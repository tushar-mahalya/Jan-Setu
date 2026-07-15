import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Jan Setu interface error", error, info);
  }

  render() {
    if (!this.state.failed) return this.props.children;

    return (
      <main className="state-page" role="alert">
        <span className="state-page__mark" aria-hidden="true">!</span>
        <h1>Something went wrong / कुछ गलत हुआ</h1>
        <p>Reload the page to continue. Your submitted complaints remain safe.</p>
        <button className="btn btn--primary" type="button" onClick={() => window.location.reload()}>
          Reload page / पेज फिर खोलें
        </button>
      </main>
    );
  }
}
