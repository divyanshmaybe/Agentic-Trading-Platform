// Register Chart.js elements once to keep components lean
import { Chart, LineElement, CategoryScale, LinearScale, PointElement, Tooltip, Filler, Legend } from "chart.js";

Chart.register(LineElement, CategoryScale, LinearScale, PointElement, Tooltip, Filler, Legend);

export { Chart };
