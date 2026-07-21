import { Component, type ErrorInfo, type ReactNode } from "react";
import { useI18n } from "../i18n/I18nContext";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  failed: boolean;
}

function ErrorFallback() {
  const { t } = useI18n();
  return (
    <main className="state-page" role="alert">
      <span className="state-page__mark" aria-hidden="true">!</span>
      <h1>{t.errorTitle}</h1>
      <p>{t.errorBody}</p>
      <button className="btn btn--primary" type="button" onClick={() => window.location.reload()}>
        {t.retry}
      </button>
    </main>
  );
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
    return <ErrorFallback />;
  }
}
