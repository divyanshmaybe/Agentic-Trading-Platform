import { Linkedin, Twitter, Facebook } from "lucide-react"

export function Footer() {
  return (
    <footer className="relative border-t border-white/10 bg-[rgba(11,18,32,0.35)] backdrop-blur-sm py-10 text-center text-white">
      <div className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-b from-transparent to-black/30" />
      <p className="text-white/80">
        © {new Date().getFullYear()} Pathway Intelligence. Empowering enterprise evolution through adaptive AI.
      </p>
      <div className="mt-4 flex justify-center gap-4">
        <a aria-label="LinkedIn" href="#" className="text-white/70 transition-colors hover:text-white hover:drop-shadow-[0_0_10px_rgba(43,108,176,0.6)]"><Linkedin /></a>
        <a aria-label="Twitter" href="#" className="text-white/70 transition-colors hover:text-white hover:drop-shadow-[0_0_10px_rgba(43,108,176,0.6)]"><Twitter /></a>
        <a aria-label="Facebook" href="#" className="text-white/70 transition-colors hover:text-white hover:drop-shadow-[0_0_10px_rgba(43,108,176,0.6)]"><Facebook /></a>
      </div>
    </footer>
  )
}
