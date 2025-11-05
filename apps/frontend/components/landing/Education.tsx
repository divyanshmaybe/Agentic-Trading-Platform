import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Container } from "@/components/shared/Container"
import { Section, SectionHeader } from "@/components/shared/Section"
import { FadeIn } from "@/components/shared/FadeIn"

export function Education() {
  return (
    <Section>
      <Container>
        <FadeIn>
          <SectionHeader title="Free and open market education" />
          <div className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-6 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Varsity</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  An extensive collection of stock market and financial lessons created by Zerodha.
                </p>
                <Link href="#" className="mt-3 inline-block text-sm font-medium text-foreground/90 hover:text-foreground">
                  Explore Varsity →
                </Link>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>TradingQ&A</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  The largest community of traders and investors to discuss and learn trading.
                </p>
                <Link href="#" className="mt-3 inline-block text-sm font-medium text-foreground/90 hover:text-foreground">
                  Visit TradingQ&A →
                </Link>
              </CardContent>
            </Card>
          </div>
        </FadeIn>
      </Container>
    </Section>
  )
}


