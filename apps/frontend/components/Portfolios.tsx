"use client"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Card, CardContent } from "@/components/ui/card"
import { portfolios } from "@/data/portfolios"

export default function Portfolios() {
  return (
    <section className="py-20 bg-gradient-to-b from-[var(--background)] to-white text-center">
      <h2 className="text-3xl font-semibold text-primary mb-6">Portfolios in Progress</h2>
      <Tabs defaultValue="highRisk" className="max-w-3xl mx-auto">
        <TabsList className="justify-center mb-8">
          <TabsTrigger value="highRisk">High Risk</TabsTrigger>
          <TabsTrigger value="lowRisk">Low Risk</TabsTrigger>
        </TabsList>
        <TabsContent value="highRisk" className="grid md:grid-cols-2 gap-6">
          {portfolios.highRisk.map((p, i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <h3 className="font-bold">{p.name}</h3>
                <p className="text-muted-foreground">{p.sector}</p>
                <p className="text-[var(--accent)]">{p.performance}</p>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
        <TabsContent value="lowRisk" className="grid md:grid-cols-2 gap-6">
          {portfolios.lowRisk.map((p, i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <h3 className="font-bold">{p.name}</h3>
                <p className="text-muted-foreground">{p.sector}</p>
                <p className="text-[var(--accent)]">{p.performance}</p>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </section>
  )
}


