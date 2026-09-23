import React from "react";

export class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || "Terjadi kesalahan saat memuat aplikasi.",
    };
  }

  componentDidCatch(error, info) {
    // Keep the technical error in the browser console for troubleshooting,
    // while showing a usable recovery screen instead of a blank white page.
    console.error("Procurement frontend render error", error, info);
  }

  handleReload = () => {
    window.location.reload();
  };

  handleHardReload = () => {
    try {
      if ("caches" in window) {
        window.caches.keys().then((keys) => Promise.all(keys.map((key) => window.caches.delete(key)))).finally(() => {
          window.location.reload();
        });
        return;
      }
    } catch (e) {
      console.warn("Gagal membersihkan cache browser", e);
    }
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="min-h-screen bg-background px-4 py-10 text-foreground">
        <div className="mx-auto max-w-xl rounded-2xl border bg-card p-6 shadow-sm">
          <div className="text-lg font-semibold">Aplikasi gagal dimuat sempurna</div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Halaman tidak akan dibiarkan kosong. Coba muat ulang aplikasi. Jika masih terjadi,
            gunakan tombol muat ulang bersih lalu kirim tangkapan layar Console browser ke admin.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={this.handleReload}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
            >
              Muat Ulang
            </button>
            <button
              type="button"
              onClick={this.handleHardReload}
              className="rounded-lg border bg-background px-4 py-2 text-sm font-semibold"
            >
              Muat Ulang Bersih
            </button>
          </div>
          {this.state.message && (
            <details className="mt-5 rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-semibold">Detail teknis</summary>
              <pre className="mt-2 whitespace-pre-wrap break-words">{this.state.message}</pre>
            </details>
          )}
        </div>
      </div>
    );
  }
}
