import React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "./ChartPrimitives.jsx";

export default function ResearchPcClassChart({ counts }) {
  const data = ["Low", "Medium", "High", "Unclassified"].map((name) => ({ name, events: counts?.[name] || 0 }));
  return <div className="home-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={data}><CartesianGrid strokeDasharray="3 3" stroke="#26364d"/><XAxis dataKey="name" stroke="#9fb7d9"/><YAxis allowDecimals={false} stroke="#9fb7d9"/><Tooltip/><Bar dataKey="events" fill="#22d3ee" radius={[6,6,0,0]}/></BarChart></ResponsiveContainer></div>;
}
