"use client"

import { useState, useEffect, useMemo } from "react"
import { Loader2, CheckCircle2, XCircle } from "lucide-react"
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { submitTrade, type TradeRequest } from "@/lib/portfolio"

interface PortfolioItem {
	ticker?: string
	percentage: number
	reasoning?: string
}

interface TradeListItem {
	ticker: string
	reasoning?: string
	percentage: number
	price_bought?: number
	amount_invested?: number
	no_of_shares_bought: number
}

interface BuyTradeModalProps {
	open: boolean
	onOpenChange: (open: boolean) => void
	finalPortfolio: PortfolioItem[]
	tradeList: TradeListItem[]
	portfolioId: string
	allocationId?: string
}

type TradeStatus = "pending" | "processing" | "success" | "failed"

interface StockFormData {
	ticker: string
	selected: boolean
	quantity: number
	suggestedQuantity: number
	order_type: "market" | "limit" | "stop" | "stop_loss" | "take_profit"
	limit_price: string
	trigger_price: string
}

interface TradeResult {
	ticker: string
	status: TradeStatus
	error?: string
	response?: any
}

export function BuyTradeModal({
	open,
	onOpenChange,
	finalPortfolio,
	tradeList,
	portfolioId,
	allocationId,
}: BuyTradeModalProps) {
	const [formData, setFormData] = useState<Record<string, StockFormData>>({})
	const [isSubmitting, setIsSubmitting] = useState(false)
	const [tradeResults, setTradeResults] = useState<Record<string, TradeResult>>({})
	const [error, setError] = useState<string | null>(null)

	// Initialize form data from finalPortfolio
	useEffect(() => {
		if (open && finalPortfolio.length > 0) {
			const initialData: Record<string, StockFormData> = {}
			
			finalPortfolio.forEach((item) => {
				if (item.ticker) {
					// Find matching trade list item for suggested quantity
					const tradeItem = tradeList.find((t) => t.ticker === item.ticker)
					const suggestedQty = tradeItem?.no_of_shares_bought || 1
					
					initialData[item.ticker] = {
						ticker: item.ticker,
						selected: false,
						quantity: suggestedQty,
						suggestedQuantity: suggestedQty,
						order_type: "market",
						limit_price: "",
						trigger_price: "",
					}
				}
			})
			
			setFormData(initialData)
			setTradeResults({})
			setError(null)
		}
	}, [open, finalPortfolio, tradeList])

	// Reset when modal closes
	useEffect(() => {
		if (!open) {
			setIsSubmitting(false)
			setTradeResults({})
			setError(null)
		}
	}, [open])

	const selectedStocks = useMemo(() => {
		return Object.values(formData).filter((stock) => stock.selected)
	}, [formData])

	const allSelected = useMemo(() => {
		const stocks = Object.values(formData)
		return stocks.length > 0 && stocks.every((stock) => stock.selected)
	}, [formData])

	const handleStockSelection = (ticker: string, selected: boolean) => {
		setFormData((prev) => ({
			...prev,
			[ticker]: {
				...prev[ticker],
				selected,
			},
		}))
	}

	const handleFieldChange = (ticker: string, field: keyof StockFormData, value: any) => {
		setFormData((prev) => ({
			...prev,
			[ticker]: {
				...prev[ticker],
				[field]: value,
			},
		}))
	}

	const handleSelectAll = () => {
		const newSelectedState = !allSelected
		setFormData((prev) => {
			const updated: Record<string, StockFormData> = {}
			Object.keys(prev).forEach((ticker) => {
				updated[ticker] = {
					...prev[ticker],
					selected: newSelectedState,
				}
			})
			return updated
		})
	}


	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault()
		setError(null)
		setIsSubmitting(true)

		if (selectedStocks.length === 0) {
			setError("Please select at least one stock to buy")
			setIsSubmitting(false)
			return
		}

		// Validate all selected stocks
		for (const stock of selectedStocks) {
			if (stock.quantity <= 0) {
				setError(`${stock.ticker}: Quantity must be greater than 0`)
				setIsSubmitting(false)
				return
			}

			if (stock.order_type === "limit" && !stock.limit_price) {
				setError(`${stock.ticker}: Limit price is required for limit orders`)
				setIsSubmitting(false)
				return
			}

			if (["stop", "stop_loss", "take_profit"].includes(stock.order_type) && !stock.trigger_price) {
				setError(`${stock.ticker}: Trigger price is required for ${stock.order_type} orders`)
				setIsSubmitting(false)
				return
			}
		}

		// Initialize all trades as pending
		const initialResults: Record<string, TradeResult> = {}
		selectedStocks.forEach((stock) => {
			initialResults[stock.ticker] = {
				ticker: stock.ticker,
				status: "pending",
			}
		})
		setTradeResults(initialResults)

		// Submit trades one by one
		let successCount = 0
		let failCount = 0

		for (const stock of selectedStocks) {
			// Update status to processing
			setTradeResults((prev) => ({
				...prev,
				[stock.ticker]: {
					ticker: stock.ticker,
					status: "processing",
				},
			}))

			try {
				const tradeRequest: TradeRequest = {
					portfolio_id: portfolioId,
					symbol: stock.ticker,
					side: "BUY",
					order_type: stock.order_type,
					quantity: stock.quantity,
					limit_price:
						stock.order_type === "limit" && stock.limit_price
							? parseFloat(stock.limit_price)
							: undefined,
					trigger_price:
						["stop", "stop_loss", "take_profit"].includes(stock.order_type) && stock.trigger_price
							? parseFloat(stock.trigger_price)
							: undefined,
					source: "longterm_strategy",
					trade_type: "cash",
					allocation_id: allocationId,
				}

				const response = await submitTrade(tradeRequest)

				// Update status to success
				setTradeResults((prev) => ({
					...prev,
					[stock.ticker]: {
						ticker: stock.ticker,
						status: "success",
						response,
					},
				}))
				successCount++
			} catch (err: any) {
				// Update status to failed
				const errorMessage = err.message || "Failed to submit trade"
				setTradeResults((prev) => ({
					...prev,
					[stock.ticker]: {
						ticker: stock.ticker,
						status: "failed",
						error: errorMessage,
					},
				}))
				failCount++
			}
		}

		setIsSubmitting(false)

		// Show summary if there were failures
		if (failCount > 0) {
			setError(`${successCount} trade(s) succeeded, ${failCount} trade(s) failed`)
		}
	}

	const getStatusIcon = (status: TradeStatus) => {
		switch (status) {
			case "processing":
				return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
			case "success":
				return <CheckCircle2 className="h-4 w-4 text-emerald-500" />
			case "failed":
				return <XCircle className="h-4 w-4 text-red-500" />
			default:
				return null
		}
	}

	const getStatusText = (status: TradeStatus) => {
		switch (status) {
			case "pending":
				return "Pending"
			case "processing":
				return "Processing..."
			case "success":
				return "Success"
			case "failed":
				return "Failed"
			default:
				return ""
		}
	}

	const portfolioItem = (item: PortfolioItem) => {
		if (!item.ticker) return null

		const stockData = formData[item.ticker]
		if (!stockData) return null

		const tradeResult = tradeResults[item.ticker]
		const isSubmittingThis = isSubmitting && tradeResult?.status === "processing"

		return (
			<div
				key={item.ticker}
				className={`rounded-lg border ${
					stockData.selected
						? "border-emerald-500/50 bg-emerald-500/5"
						: "border-white/10 bg-white/5"
				} p-4 transition-colors`}
			>
				<div className="flex items-start gap-3">
					<input
						type="checkbox"
						checked={stockData.selected}
						onChange={(e) => handleStockSelection(item.ticker!, e.target.checked)}
						disabled={isSubmitting}
						className="mt-1 h-4 w-4 rounded border-white/20 bg-white/10 text-emerald-500 focus:ring-emerald-500 disabled:opacity-50"
					/>
					<div className="flex-1">
						<div className="flex items-center gap-3">
							<span className="font-semibold text-white">{item.ticker}</span>
							<span className="text-sm text-white/60">{item.percentage.toFixed(2)}%</span>
							{tradeResult && (
								<div className="flex items-center gap-2">
									{getStatusIcon(tradeResult.status)}
									<span className="text-sm text-white/70">{getStatusText(tradeResult.status)}</span>
								</div>
							)}
						</div>

						{item.reasoning && (
							<p className="mt-1 text-sm text-white/50">{item.reasoning}</p>
						)}

						{stockData.selected && (
							<div className="mt-4 space-y-3">
								<div className="space-y-2">
									<label className="text-sm font-medium text-white/70">
										Quantity <span className="text-red-500">*</span>
									</label>
									<div className="flex items-center gap-2">
										<input
											type="number"
											min="1"
											value={stockData.quantity}
											onChange={(e) =>
												handleFieldChange(item.ticker!, "quantity", parseInt(e.target.value) || 0)
											}
											disabled={isSubmittingThis}
											className="flex-1 rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
										/>
										<span className="text-xs text-white/50">
											Suggested: {stockData.suggestedQuantity}
										</span>
									</div>
								</div>

								<div className="space-y-2">
									<label className="text-sm font-medium text-white/70">
										Order Type <span className="text-red-500">*</span>
									</label>
									<select
										value={stockData.order_type}
										onChange={(e) =>
											handleFieldChange(
												item.ticker!,
												"order_type",
												e.target.value as StockFormData["order_type"]
											)
										}
										disabled={isSubmittingThis}
										className="w-full rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
									>
										<option value="market">Market</option>
										<option value="limit">Limit</option>
										<option value="stop">Stop</option>
										<option value="stop_loss">Stop Loss</option>
										<option value="take_profit">Take Profit</option>
									</select>
								</div>

								{stockData.order_type === "limit" && (
									<div className="space-y-2">
										<label className="text-sm font-medium text-white/70">
											Limit Price <span className="text-red-500">*</span>
										</label>
										<input
											type="number"
											step="0.01"
											min="0.01"
											value={stockData.limit_price}
											onChange={(e) => handleFieldChange(item.ticker!, "limit_price", e.target.value)}
											disabled={isSubmittingThis}
											placeholder="Enter limit price"
											className="w-full rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
										/>
									</div>
								)}

								{["stop", "stop_loss", "take_profit"].includes(stockData.order_type) && (
									<div className="space-y-2">
										<label className="text-sm font-medium text-white/70">
											Trigger Price <span className="text-red-500">*</span>
										</label>
										<input
											type="number"
											step="0.01"
											min="0.01"
											value={stockData.trigger_price}
											onChange={(e) =>
												handleFieldChange(item.ticker!, "trigger_price", e.target.value)
											}
											disabled={isSubmittingThis}
											placeholder="Enter trigger price"
											className="w-full rounded-md border border-white/20 bg-white/10 px-3 py-2 text-sm text-white placeholder:text-white/40 focus:outline-none focus:ring-2 focus:ring-emerald-500 disabled:opacity-50"
										/>
									</div>
								)}

								{tradeResult?.status === "failed" && tradeResult.error && (
									<div className="rounded-md bg-red-500/10 border border-red-500/20 px-3 py-2 text-sm text-red-400">
										{tradeResult.error}
									</div>
								)}

								{tradeResult?.status === "success" && tradeResult.response && (
									<div className="rounded-md bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-sm text-emerald-400">
										Trade submitted successfully!
									</div>
								)}
							</div>
						)}
					</div>
				</div>
			</div>
		)
	}

	const hasAnyResults = Object.keys(tradeResults).length > 0
	const allCompleted = hasAnyResults && Object.values(tradeResults).every((r) => r.status !== "pending" && r.status !== "processing")
	const successCount = Object.values(tradeResults).filter((r) => r.status === "success").length
	const failCount = Object.values(tradeResults).filter((r) => r.status === "failed").length

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-[#0c0c0c] border-white/10 text-[#fafafa]">
				<DialogHeader>
					<div className="flex items-center justify-between">
						<div>
							<DialogTitle className="text-xl font-semibold text-white">Buy Stocks from Portfolio</DialogTitle>
							<DialogDescription className="text-white/60">
								Select stocks from the recommended portfolio and customize trade parameters
							</DialogDescription>
						</div>
						<Button
							type="button"
							variant="outline"
							onClick={handleSelectAll}
							disabled={isSubmitting || finalPortfolio.length === 0}
							className="border-white/20 bg-white/10 text-white hover:bg-white/20 disabled:opacity-50"
						>
							{allSelected ? "Deselect All" : "Select All"}
						</Button>
					</div>
				</DialogHeader>

				<form onSubmit={handleSubmit} className="space-y-4">
					<div className="space-y-3 max-h-[50vh] overflow-y-auto pr-2">
						{finalPortfolio.map((item) => portfolioItem(item))}
					</div>

					{selectedStocks.length > 0 && (
						<div className="rounded-lg border border-white/10 bg-white/5 p-3">
							<p className="text-sm text-white/70">
								{selectedStocks.length} stock(s) selected
							</p>
						</div>
					)}

					{allCompleted && hasAnyResults && (
						<div
							className={`rounded-lg border p-3 ${
								failCount > 0
									? "border-yellow-500/50 bg-yellow-500/10"
									: "border-emerald-500/50 bg-emerald-500/10"
							}`}
						>
							<p className="text-sm font-medium text-white">
								{successCount} trade(s) succeeded{failCount > 0 ? `, ${failCount} trade(s) failed` : ""}
							</p>
						</div>
					)}

					{error && (
						<div className="rounded-md bg-red-500/10 border border-red-500/20 px-3 py-2 text-sm text-red-400">
							{error}
						</div>
					)}

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
							className="border-white/20 bg-white/10 text-white hover:bg-white/20"
						>
							Close
						</Button>
						<Button
							type="submit"
							disabled={isSubmitting || selectedStocks.length === 0}
							className="bg-emerald-500 hover:bg-emerald-600 text-white disabled:opacity-50"
						>
							{isSubmitting ? (
								<>
									<Loader2 className="mr-2 h-4 w-4 animate-spin" />
									Submitting Trades...
								</>
							) : (
								`Buy Selected Stocks (${selectedStocks.length})`
							)}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	)
}

