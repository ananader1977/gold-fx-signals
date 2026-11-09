import Perplexity from "@perplexity-ai/perplexity_ai";

const client = new Perplexity(); // reads PERPLEXITY_API_KEY from the environment

const response = await client.responses.create({
  effort: "low",
  input: "Summarize the latest changes to the Perplexity Agent API.",
});

console.log(`Model used: ${response.model}`);
console.log(response.output_text);
