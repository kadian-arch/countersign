// The same markup and styles as the page shows before the app has loaded (see index.html), so nothing jumps
export function Loader({ line = "Opening the dashboard" }: { line?: string }) {
  return (
    <div className="boot" role="status" aria-live="polite">
      <svg className="mark" viewBox="0 0 40 40" aria-hidden="true">
        <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2fd9ff" /><stop offset=".5" stopColor="#6a82ff" /><stop offset="1" stopColor="#c866ff" /></linearGradient></defs>
        <circle className="ring" cx="20" cy="20" r="14.5" fill="none" stroke="url(#bg)" strokeWidth="2.6" strokeLinecap="round" />
        <path className="tick" d="M12.6 20.9 L17.7 25.6 L27.6 14.2" fill="none" stroke="url(#bg)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="boot-title">Countersign</p>
      <p className="boot-line"><span>{line}</span></p>
      <div className="boot-tiles" aria-hidden="true"><i /><i /><i /><i /></div>
    </div>
  );
}
