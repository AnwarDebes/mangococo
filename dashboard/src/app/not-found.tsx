import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60dvh] gap-6 animate-fade-in">
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-goblin-500/10 border border-goblin-500/20">
        <svg
          width="40"
          height="40"
          viewBox="0 0 256 256"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="nfSkin" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" style={{ stopColor: "#7cb342" }} />
              <stop offset="100%" style={{ stopColor: "#558b2f" }} />
            </linearGradient>
          </defs>
          <ellipse cx="128" cy="140" rx="65" ry="60" fill="url(#nfSkin)" />
          <ellipse cx="102" cy="130" rx="16" ry="20" fill="#fff" />
          <ellipse cx="105" cy="132" rx="9" ry="11" fill="#2d2d2d" />
          <ellipse cx="154" cy="130" rx="16" ry="20" fill="#fff" />
          <ellipse cx="157" cy="132" rx="9" ry="11" fill="#2d2d2d" />
          <line
            x1="105"
            y1="175"
            x2="151"
            y2="175"
            stroke="#2d2d2d"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
      </div>

      <div className="text-center max-w-md px-4">
        <h2 className="text-4xl font-bold text-white mb-2">404</h2>
        <p className="text-sm text-gray-400 mb-6">
          This goblin couldn&apos;t find the page you&apos;re looking for.
        </p>
        <Link href="/" className="btn-goblin text-sm px-6 py-2.5 inline-block">
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
