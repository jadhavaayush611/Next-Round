import { Sparkles, Cpu, FileText, CheckCircle, ArrowRight } from "lucide-react";

export default function Home() {
  return (
    <div className="relative min-h-screen bg-[#09090b] text-zinc-100 overflow-hidden flex flex-col justify-between selection:bg-indigo-500 selection:text-white">
      {/* Dynamic Background mesh gradients */}
      <div className="absolute top-0 left-1/4 -translate-x-1/2 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-10 right-1/4 translate-x-1/2 w-[400px] h-[400px] bg-violet-600/10 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute top-1/3 right-10 w-[300px] h-[300px] bg-purple-500/5 rounded-full blur-[90px] pointer-events-none" />

      {/* Navigation Header */}
      <header className="border-b border-zinc-800/60 bg-zinc-950/40 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2 font-bold text-xl tracking-tight text-white">
            <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
              NextRound
            </span>
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700 font-semibold tracking-wider">
              v1.0-alpha
            </span>
          </div>
          <nav className="hidden md:flex items-center gap-8 text-sm text-zinc-400 font-medium">
            <a href="#features" className="hover:text-zinc-200 transition-colors">
              Features
            </a>
            <a href="#roadmap" className="hover:text-zinc-200 transition-colors">
              Roadmap
            </a>
            <a
              href="file:///D:/NextRound/architecture.md"
              className="hover:text-zinc-200 transition-colors"
            >
              Architecture
            </a>
          </nav>
          <div className="flex items-center gap-4">
            <button className="text-zinc-400 hover:text-zinc-200 text-sm font-semibold transition-colors px-4 py-2">
              Sign In
            </button>
            <button className="relative group overflow-hidden px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-purple-600 text-white font-semibold text-sm transition-all hover:shadow-[0_0_20px_rgba(99,102,241,0.4)]">
              <span className="relative z-10">Get Started</span>
              <div className="absolute inset-0 bg-gradient-to-r from-purple-600 to-pink-500 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Hero Section */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 flex flex-col justify-center items-center py-20 md:py-32 text-center relative z-10">
        {/* Accent Sub-badge */}
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-indigo-500/30 bg-indigo-500/5 text-indigo-300 text-xs font-semibold tracking-wide mb-8 animate-pulse">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          <span>The placement readiness platform for Indian engineers</span>
        </div>

        {/* Principal Heading */}
        <h1 className="text-4xl md:text-6xl lg:text-7xl font-extrabold tracking-tight text-white mb-6 max-w-4xl leading-tight">
          NextRound — <br />
          <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
            Placement Readiness Platform
          </span>
        </h1>

        {/* High-quality description subtext */}
        <p className="text-zinc-400 text-lg md:text-xl max-w-2xl mb-12 leading-relaxed font-normal">
          Evaluate your preparation beyond resume checklists. Analyze ATS scores, match job
          descriptions, detect skill gaps, track DSA topics, and generate custom study roadmaps
          automatically.
        </p>

        {/* CTA Buttons */}
        <div className="flex flex-col sm:flex-row gap-4 mb-24 w-full justify-center px-4">
          <button className="w-full sm:w-auto h-12 px-8 rounded-lg bg-white text-black font-semibold hover:bg-zinc-200 transition-all shadow-[0_4px_20px_rgba(255,255,255,0.15)] flex items-center justify-center gap-2 group cursor-pointer">
            Get Placement Assessment
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </button>
          <a
            href="file:///D:/NextRound/architecture.md"
            className="w-full sm:w-auto h-12 px-8 rounded-lg border border-zinc-800 bg-zinc-950/60 backdrop-blur-sm text-zinc-300 hover:text-white hover:border-zinc-600 transition-colors flex items-center justify-center gap-2 cursor-pointer"
          >
            Read System Architecture
          </a>
        </div>

        {/* Feature Highlights Grid */}
        <section
          id="features"
          className="w-full grid grid-cols-1 md:grid-cols-3 gap-6 text-left py-12 border-t border-zinc-800/40"
        >
          {/* Card 1 */}
          <div className="p-6 rounded-xl border border-zinc-800/60 bg-zinc-950/20 backdrop-blur-sm hover:border-indigo-500/50 hover:bg-zinc-900/10 transition-all duration-300 group">
            <div className="w-10 h-10 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-400 mb-4 group-hover:bg-indigo-500/20 transition-colors">
              <FileText className="w-5 h-5" />
            </div>
            <h3 className="text-lg font-bold text-white mb-2 group-hover:text-indigo-300 transition-colors">
              Resume Parsing & ATS
            </h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Extract raw structures from PDF/DOCX templates and score formatting, density, and
              keyword alignment out of 100.
            </p>
          </div>

          {/* Card 2 */}
          <div className="p-6 rounded-xl border border-zinc-800/60 bg-zinc-950/20 backdrop-blur-sm hover:border-purple-500/50 hover:bg-zinc-900/10 transition-all duration-300 group">
            <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center text-purple-400 mb-4 group-hover:bg-purple-500/20 transition-colors">
              <Cpu className="w-5 h-5" />
            </div>
            <h3 className="text-lg font-bold text-white mb-2 group-hover:text-purple-300 transition-colors">
              NLP Job Matching
            </h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Leverage spaCy pipelines and semantic vectors to align resume items against JDs and
              identify critical tech stack gaps.
            </p>
          </div>

          {/* Card 3 */}
          <div className="p-6 rounded-xl border border-zinc-800/60 bg-zinc-950/20 backdrop-blur-sm hover:border-pink-500/50 hover:bg-zinc-900/10 transition-all duration-300 group">
            <div className="w-10 h-10 rounded-lg bg-pink-500/10 flex items-center justify-center text-pink-400 mb-4 group-hover:bg-pink-500/20 transition-colors">
              <CheckCircle className="w-5 h-5" />
            </div>
            <h3 className="text-lg font-bold text-white mb-2 group-hover:text-pink-300 transition-colors">
              Readiness & Roadmap
            </h3>
            <p className="text-sm text-zinc-400 leading-relaxed">
              Synthesize resume, project complexity, skill matrix, DSA coverage, and mock interview
              logs into a single mentor dashboard.
            </p>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-900 bg-zinc-950 py-8 z-10">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-zinc-500 font-medium">
          <div>© 2026 NextRound Monorepo. All rights reserved.</div>
          <div className="flex gap-6">
            <a
              href="file:///D:/NextRound/LICENSE"
              className="hover:text-zinc-400 transition-colors"
            >
              License
            </a>
            <a
              href="file:///D:/NextRound/README.md"
              className="hover:text-zinc-400 transition-colors"
            >
              Readme
            </a>
            <a
              href="file:///D:/NextRound/architecture.md"
              className="hover:text-zinc-400 transition-colors"
            >
              System Architecture
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
