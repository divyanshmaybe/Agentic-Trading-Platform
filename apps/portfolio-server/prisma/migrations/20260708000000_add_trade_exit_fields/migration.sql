ALTER TABLE "trades" ADD COLUMN "exit_quantity" INTEGER;
ALTER TABLE "trades" ADD COLUMN "exit_price" DECIMAL(20,4);
ALTER TABLE "trades" ADD COLUMN "exit_time" TIMESTAMP(3);
ALTER TABLE "trades" ADD COLUMN "exit_reason" TEXT;
