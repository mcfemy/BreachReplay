import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="min-h-screen bg-breach-bg flex flex-col items-center justify-center text-center p-6">
      <div className="text-7xl font-black font-mono text-breach-accent mb-3">404</div>
      <h1 className="text-lg font-bold text-breach-text uppercase tracking-widest mb-2">
        Page Not Found
      </h1>
      <p className="text-xs text-breach-muted max-w-xs mb-8">
        The page you are looking for does not exist or has been moved.
      </p>
      <Link
        to="/scenarios"
        className="bg-breach-accent hover:bg-red-600 text-white px-6 py-2 rounded text-xs uppercase tracking-widest font-bold transition-colors"
      >
        Go to Dashboard
      </Link>
    </div>
  );
}
