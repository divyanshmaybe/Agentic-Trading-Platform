"use client"

import { useState, useEffect } from "react"
import { Loader2 } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { getPortfolio, submitTrade, type TradeRequest, type Portfolio } from "@/lib/portfolio"
import type { KafkaNotification } from "../types"
import { toRecord } from "../notification-utils"

type TradeSide = "BUY" | "SELL"

type TradeModalProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  notification: KafkaNotification
  side?: TradeSide
}

export function TradeModal({ open, onOpenChange, notification, side = "BUY" }: TradeModalProps) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [loading, setLoading] = useState(false)
  const [fetchingPortfolio, setFetchingPortfolio] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const [formData, setFormData] = useState({
    portfolio_id: "",
    quantity: 1,
    order_type: "market" as "market" | "limit",
    limit_price: "",
  })

  const notificationData = toRecord(notification.data)
  const symbol = (notificationData?.symbol as string) || ""
  const isBuy = side === "BUY"

  // Fetch portfolio when modal opens
  useEffect(() => {
    if (open && !portfolio) {
      setFetchingPortfolio(true)
      setError(null)
      getPortfolio()
        .then((data) => {
          setPortfolio(data)
          setFormData((prev) => ({ ...prev, portfolio_id: data.id }))
        })
        .catch((err) => {
          setError(err.message || "Failed to fetch portfolio")
        })
        .finally(() => {
          setFetchingPortfolio(false)
        })
    }
  }, [open, portfolio])

  // Reset form when modal closes
  useEffect(() => {
    if (!open) {
      setFormData({
        portfolio_id: portfolio?.id || "",
        quantity: 1,
        order_type: "market",
        limit_price: "",
      })
      setError(null)
      setSuccess(false)
    }
  }, [open, portfolio])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      if (!formData.portfolio_id) {
        throw new Error("Please select a portfolio")
      }

      if (formData.quantity <= 0) {
        throw new Error("Quantity must be greater than 0")
      }

      if (formData.order_type === "limit" && !formData.limit_price) {
        throw new Error("Limit price is required for limit orders")
      }

      const tradeRequest: TradeRequest = {
        portfolio_id: formData.portfolio_id,
        symbol,
        side,
        order_type: formData.order_type,
        quantity: formData.quantity,
        limit_price:
          formData.order_type === "limit" && formData.limit_price
            ? parseFloat(formData.limit_price)
            : undefined,
        source: "intraday_signal",
      }

      await submitTrade(tradeRequest)
      setSuccess(true)

      // Wait 1 second before closing
      setTimeout(() => {
        onOpenChange(false)
      }, 1000)
    } catch (err: any) {
      // Handle different error types with user-friendly messages
      let errorMessage = "Failed to submit trade. Please try again."
      
      // The request function in portfolio.ts throws Error objects with the message
      if (err.message) {
        errorMessage = err.message
        
        // Check for specific error patterns
        if (errorMessage.includes("502") || errorMessage.includes("Bad Gateway")) {
          errorMessage = "Market data service is unavailable. The system cannot fetch live prices right now. Please check if the market data service is running and try again."
        } else if (errorMessage.includes("403") || errorMessage.includes("Forbidden")) {
          errorMessage = "You don't have permission to execute this trade."
        } else if (errorMessage.includes("404") || errorMessage.includes("not found")) {
          errorMessage = "Portfolio not found. Please refresh and try again."
        } else if (errorMessage.includes("400") || errorMessage.includes("Bad Request")) {
          errorMessage = "Invalid trade request. Please check your inputs."
        }
      }
      
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{isBuy ? "Place Buy Order" : "Place Sell Order"}</DialogTitle>
          <DialogDescription>
            Submit a {isBuy ? "buy" : "sell"} order for this trading signal
          </DialogDescription>
        </DialogHeader>

        {fetchingPortfolio ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Loading portfolio...</span>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="symbol" className="text-sm font-medium">
                Symbol
              </label>
              <input
                id="symbol"
                type="text"
                value={symbol}
                readOnly
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="portfolio" className="text-sm font-medium">
                Portfolio <span className="text-destructive">*</span>
              </label>
              <select
                id="portfolio"
                value={formData.portfolio_id}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, portfolio_id: e.target.value }))
                }
                required
                disabled={loading || !portfolio}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {portfolio ? (
                  <option value={portfolio.id}>{portfolio.portfolio_name}</option>
                ) : (
                  <option value="">No portfolio available</option>
                )}
              </select>
            </div>

            <div className="space-y-2">
              <label htmlFor="quantity" className="text-sm font-medium">
                Quantity <span className="text-destructive">*</span>
              </label>
              <input
                id="quantity"
                type="number"
                min="1"
                value={formData.quantity}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, quantity: parseInt(e.target.value) || 1 }))
                }
                required
                disabled={loading}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="order_type" className="text-sm font-medium">
                Order Type <span className="text-destructive">*</span>
              </label>
              <select
                id="order_type"
                value={formData.order_type}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    order_type: e.target.value as "market" | "limit",
                    limit_price: e.target.value === "market" ? "" : prev.limit_price,
                  }))
                }
                required
                disabled={loading}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="market">Market</option>
                <option value="limit">Limit</option>
              </select>
            </div>

            {formData.order_type === "limit" && (
              <div className="space-y-2">
                <label htmlFor="limit_price" className="text-sm font-medium">
                  Limit Price <span className="text-destructive">*</span>
                </label>
                <input
                  id="limit_price"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={formData.limit_price}
                  onChange={(e) =>
                    setFormData((prev) => ({ ...prev, limit_price: e.target.value }))
                  }
                  required
                  disabled={loading}
                  placeholder="Enter limit price"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
            )}

            {error && (
              <div className="rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            {success && (
              <div className="rounded-md bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-sm text-emerald-600 dark:text-emerald-400">
                Trade submitted successfully!
              </div>
            )}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={loading || fetchingPortfolio || success}>
                {loading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  "Submit Trade"
                )}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

