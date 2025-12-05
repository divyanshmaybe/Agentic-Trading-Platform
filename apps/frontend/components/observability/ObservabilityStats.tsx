import { motion } from "framer-motion"
import { Activity, CheckCircle, XCircle, Clock, Zap, BarChart2, Hash } from "lucide-react"
import { ObservabilityStats } from "@/lib/observability"

interface StatsCardProps {
	title: string
	value: string | number
	icon: React.ReactNode
	trend?: string
	trendUp?: boolean
	color: string
}

function StatsCard({ title, value, icon, color }: StatsCardProps) {
	return (
		<motion.div
			initial={{ opacity: 0, y: 20 }}
			animate={{ opacity: 1, y: 0 }}
			className="relative overflow-hidden rounded-xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm transition-all hover:bg-white/10"
		>
			<div className={`absolute -right-4 -top-4 h-24 w-24 rounded-full ${color} opacity-10 blur-2xl`} />

			<div className="relative z-10 flex items-start justify-between">
				<div>
					<p className="text-sm font-medium text-gray-400">{title}</p>
					<h3 className="mt-2 text-3xl font-bold text-white">{value}</h3>
				</div>
				<div className={`rounded-lg p-2 ${color} bg-opacity-20`}>
					{icon}
				</div>
			</div>
		</motion.div>
	)
}

interface ObservabilityStatsDisplayProps {
	stats: ObservabilityStats | null
	loading: boolean
}

export function ObservabilityStatsDisplay({ stats, loading }: ObservabilityStatsDisplayProps) {
	if (loading || !stats) {
		return (
			<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
				{[...Array(4)].map((_, i) => (
					<div key={i} className="h-32 animate-pulse rounded-xl border border-white/10 bg-white/5" />
				))}
			</div>
		)
	}

	return (
		<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
			<StatsCard
				title="Total Analyses"
				value={stats.total_analyses}
				icon={<Activity className="h-5 w-5 text-blue-400" />}
				color="bg-blue-500"
			/>
			<StatsCard
				title="Success Rate"
				value={`${Math.round((stats.completed / stats.total_analyses) * 100) || 0}%`}
				icon={<CheckCircle className="h-5 w-5 text-green-400" />}
				color="bg-green-500"
			/>
			<StatsCard
				title="Avg Latency"
				value={`${Math.round(stats.avg_latency_ms)}ms`}
				icon={<Clock className="h-5 w-5 text-yellow-400" />}
				color="bg-yellow-500"
			/>
			<StatsCard
				title="Failed"
				value={stats.failed}
				icon={<XCircle className="h-5 w-5 text-red-400" />}
				color="bg-red-500"
			/>
		</div>
	)
}
