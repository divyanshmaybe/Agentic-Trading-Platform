import Image from "next/image"
import { motion } from "framer-motion"

export default function About() {
	return (
		<section className="py-20 bg-background flex flex-col md:flex-row items-center justify-around px-8">
			<motion.div
				initial={{ opacity: 0, x: -30 }}
				whileInView={{ opacity: 1, x: 0 }}
				transition={{ duration: 0.7 }}
				viewport={{ once: true }}
				className="max-w-md"
			>
				<h2 className="text-3xl font-semibold text-primary mb-4">Pathway to Performance</h2>
				<p className="text-muted-foreground">
					Pathway integrates adaptive intelligence, performance metrics, and human oversight to redefine how enterprises balance high-risk and low-risk portfolios.
				</p>
			</motion.div>
			<Image src="/images/about-img.jpg" alt="About Image" width={400} height={400} className="rounded-2xl shadow-lg" />
		</section>
	)
}


