"""
RAG Pipeline - Retrieval Augmented Generation for Stock Prediction.
====================================================================

This is the core intelligence layer that:
1. Retrieves relevant social media posts from ChromaDB (vector search)
2. Enriches with structured data from SQLite (signals, mentions)
3. Builds a context prompt for the LLM
4. Gets prediction from LLM (Gemini / OpenAI)
5. Returns structured prediction with reasoning

Supports: Google Gemini, OpenAI GPT-4, or local Ollama models.
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv

# Suppress SSL warnings for corporate proxy environments
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .database import Database, Stock, StockSignal, StockMention, RawPost
from .vector_store import VectorStore
from .sentiment import SentimentAnalyzer

load_dotenv()


# ──────────────────────────────────────────────────────────────────────
# LLM PROVIDERS
# ──────────────────────────────────────────────────────────────────────

class LLMProvider:
    """Base class for LLM providers."""

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, api_key: str = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model = model
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set")

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(
                model=self.model,
                contents=full_prompt,
            )
            return response.text
        except ImportError:
            # Fallback to REST API
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
            }
            resp = requests.post(
                f"{url}?key={self.api_key}",
                json=payload, timeout=60, verify=False
            )
            resp.raise_for_status()
            return resp.json()['candidates'][0]['content']['parts'][0]['text']


class OpenAIProvider(LLMProvider):
    """OpenAI API provider (GPT-4, etc.)."""

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        import requests
        url = "https://api.openai.com/v1/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            url,
            json={"model": self.model, "messages": messages, "temperature": 0.3},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60, verify=False
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']


class OllamaProvider(LLMProvider):
    """Local Ollama provider (free, private)."""

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        import requests
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
                "stream": False,
            },
            timeout=120
        )
        resp.raise_for_status()
        return resp.json()['response']


# ──────────────────────────────────────────────────────────────────────
# RAG PIPELINE
# ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Indian stock market analyst. Your role is to analyze 
social media sentiment and discussions about stocks traded on NSE and BSE exchanges.

You will be given:
1. Recent social media posts mentioning a specific stock
2. Aggregated sentiment signals
3. Technical and fundamental analysis mentions

Based on this data, provide:
1. A clear PREDICTION (Bullish/Bearish/Neutral) with confidence level
2. Key factors driving the prediction
3. Risk factors to consider
4. Suggested action (Buy/Sell/Hold/Watch)
5. Short-term (1-3 days) and medium-term (1-2 weeks) outlook

IMPORTANT:
- Base your analysis ONLY on the provided data
- Clearly state confidence level (Low/Medium/High)
- Highlight conflicting signals if any
- Mention if data is insufficient for reliable prediction
- Do NOT fabricate data points
- Always include risk disclaimer

Format your response as JSON with this structure:
{
    "prediction": "Bullish/Bearish/Neutral",
    "confidence": "Low/Medium/High",
    "confidence_score": 0.0-1.0,
    "short_term_outlook": "description",
    "medium_term_outlook": "description",
    "suggested_action": "Buy/Sell/Hold/Watch",
    "target_price_range": {"low": null, "high": null},
    "stop_loss_suggested": null,
    "key_factors": ["factor1", "factor2"],
    "risk_factors": ["risk1", "risk2"],
    "conflicting_signals": ["signal1"],
    "reasoning": "detailed explanation",
    "data_quality": "Sufficient/Limited/Insufficient",
    "disclaimer": "This is AI-generated analysis based on social media sentiment. Not financial advice."
}"""


class RAGPipeline:
    """
    Main RAG pipeline that ties everything together.
    
    Flow:
    1. User queries for a stock prediction
    2. Pipeline retrieves relevant posts from ChromaDB
    3. Enriches with structured signals from SQLite
    4. Constructs context prompt
    5. Sends to LLM for prediction
    6. Parses and returns structured result
    """

    def __init__(self, db: Database, vector_store: VectorStore,
                 llm_provider: LLMProvider):
        self.db = db
        self.vector_store = vector_store
        self.llm = llm_provider
        self.sentiment_analyzer = SentimentAnalyzer()

    def predict(self, stock_symbol: str, 
                lookback_hours: int = 72,
                max_posts: int = 20) -> Dict:
        """
        Generate a prediction for a stock based on social media intelligence.
        
        Args:
            stock_symbol: NSE/BSE stock symbol (e.g. "RELIANCE")
            lookback_hours: How far back to look for posts
            max_posts: Maximum posts to include in RAG context
            
        Returns:
            Prediction dict with reasoning
        """
        # 1. Find the stock
        stocks = self.db.search_stock(stock_symbol)
        if not stocks:
            return {"error": f"Stock '{stock_symbol}' not found in database"}
        stock = stocks[0]

        # 2. Retrieve relevant posts from vector store
        vector_results = self.vector_store.search(
            query=f"{stock.symbol} {stock.name} stock market prediction analysis",
            n_results=max_posts,
            stock_symbol=stock.symbol,
        )

        # Also try some focused queries
        for query in [
            f"{stock.symbol} buy sell target",
            f"{stock.name} results earnings analysis",
        ]:
            extra = self.vector_store.search(query=query, n_results=5)
            vector_results.extend(extra)

        # Deduplicate
        seen_ids = set()
        unique_results = []
        for r in vector_results:
            if r['id'] not in seen_ids:
                unique_results.append(r)
                seen_ids.add(r['id'])
        vector_results = unique_results[:max_posts]

        # 3. Get structured signals from SQLite
        latest_signal = self.db.get_latest_signal(stock.id)
        since = datetime.utcnow() - timedelta(hours=lookback_hours)
        mentions = self.db.get_mentions_for_stock(stock.id, since=since, limit=50)

        # 4. Build context prompt
        context = self._build_context(stock, vector_results, mentions, latest_signal)

        # 5. Query LLM
        try:
            response_text = self.llm.generate(context, SYSTEM_PROMPT)
            prediction = self._parse_prediction(response_text)
        except Exception as e:
            prediction = {
                "error": f"LLM generation failed: {str(e)}",
                "fallback_prediction": self._fallback_prediction(mentions, latest_signal),
            }

        # 6. Enrich with metadata
        prediction['stock'] = {
            'symbol': stock.symbol,
            'name': stock.name,
            'exchange': stock.exchange,
            'sector': stock.sector,
        }
        prediction['data_summary'] = {
            'posts_analyzed': len(vector_results),
            'mentions_found': len(mentions),
            'lookback_hours': lookback_hours,
            'generated_at': datetime.utcnow().isoformat(),
        }

        return prediction

    def _build_context(self, stock: Stock, posts: List[Dict],
                        mentions: List[StockMention],
                        signal: Optional[StockSignal]) -> str:
        """Build the context prompt for the LLM."""
        parts = []
        
        parts.append(f"## Stock: {stock.symbol} - {stock.name}")
        parts.append(f"Exchange: {stock.exchange} | Sector: {stock.sector}")
        parts.append("")

        # Signal summary
        if signal:
            parts.append("## Latest Aggregated Signal")
            parts.append(f"- Signal: {signal.signal_strength.value if signal.signal_strength else 'N/A'}")
            parts.append(f"- Avg Sentiment: {signal.avg_sentiment:.3f}" if signal.avg_sentiment else "")
            parts.append(f"- Total Mentions: {signal.total_mentions}")
            parts.append(f"- Bullish: {signal.bullish_count} | Bearish: {signal.bearish_count} | Neutral: {signal.neutral_count}")
            parts.append(f"- Technical mentions: {signal.technical_mentions} | Fundamental: {signal.fundamental_mentions}")
            parts.append(f"- Predicted Direction: {signal.predicted_direction}")
            parts.append("")

        # Mention details
        if mentions:
            parts.append("## Recent Stock Mentions Summary")
            actions = [m.action_suggested for m in mentions if m.action_suggested]
            targets = [m.target_price for m in mentions if m.target_price]
            if actions:
                from collections import Counter
                parts.append(f"- Actions suggested: {dict(Counter(actions))}")
            if targets:
                parts.append(f"- Target prices mentioned: {[round(t, 2) for t in targets[:5]]}")
            parts.append("")

        # Social media posts (RAG context)
        if posts:
            parts.append(f"## Recent Social Media Posts ({len(posts)} posts)")
            parts.append("")
            for i, post in enumerate(posts[:max(15, len(posts))], 1):
                meta = post.get('metadata', {})
                text = post.get('text', '')[:300]
                platform = meta.get('platform', 'unknown')
                author = meta.get('author', 'unknown')
                date = meta.get('posted_at', 'unknown')
                
                parts.append(f"### Post {i} [{platform}] by {author} ({date})")
                parts.append(text)
                parts.append("")

        parts.append("---")
        parts.append(f"Based on the above data, provide your analysis and prediction for {stock.symbol}.")

        return "\n".join(parts)

    def _parse_prediction(self, response: str) -> Dict:
        """Parse LLM response, handling JSON or plain text."""
        # Try to extract JSON
        try:
            # Find JSON block in response
            json_match = response
            if '```json' in response:
                json_match = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                json_match = response.split('```')[1].split('```')[0]
            
            return json.loads(json_match)
        except (json.JSONDecodeError, IndexError):
            # Return as plain text reasoning
            return {
                "prediction": "See reasoning",
                "reasoning": response,
                "confidence": "Low",
                "disclaimer": "Could not parse structured prediction from LLM response.",
            }

    def _fallback_prediction(self, mentions: List[StockMention],
                              signal: Optional[StockSignal]) -> Dict:
        """Generate a simple prediction without LLM (pure rule-based)."""
        if signal and signal.avg_sentiment is not None:
            if signal.avg_sentiment > 0.3:
                return {"prediction": "Bullish", "confidence": "Medium", 
                        "reasoning": f"Avg sentiment {signal.avg_sentiment:.2f} from {signal.total_mentions} mentions"}
            elif signal.avg_sentiment < -0.3:
                return {"prediction": "Bearish", "confidence": "Medium",
                        "reasoning": f"Avg sentiment {signal.avg_sentiment:.2f} from {signal.total_mentions} mentions"}
        
        return {"prediction": "Neutral", "confidence": "Low",
                "reasoning": "Insufficient data for reliable prediction"}

    def query(self, question: str, n_results: int = 10) -> str:
        """
        General RAG query — ask any question about stocks/markets.
        Retrieves relevant context and answers via LLM.
        """
        # Semantic search for relevant posts
        results = self.vector_store.search(query=question, n_results=n_results)

        context_parts = ["## Relevant Social Media Posts\n"]
        for i, r in enumerate(results, 1):
            meta = r.get('metadata', {})
            context_parts.append(
                f"{i}. [{meta.get('platform', '?')}] {r['text'][:200]}"
            )

        context = "\n".join(context_parts)
        prompt = f"{context}\n\n---\nQuestion: {question}\n\nAnswer based on the above social media data:"

        return self.llm.generate(prompt, system_prompt="You are a helpful stock market analyst. Answer based only on the provided data.")
