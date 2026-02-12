
import { GoogleGenAI, Type } from "@google/genai";
import { AnalysisResult, Platform, AnalysisMode } from "../types";

const analysisSchema = {
  type: Type.OBJECT,
  properties: {
    summary: {
      type: Type.STRING,
      description: "A concise executive summary based ONLY on the provided search context. If no data found, state 'No data available from search results'.",
    },
    data_source_verified: {
      type: Type.BOOLEAN,
      description: "Set to true ONLY if the response is based on actual search results. Set to false if no relevant data was found."
    },
    sentiment: {
      type: Type.OBJECT,
      properties: {
        score: { type: Type.NUMBER, description: "Sentiment score -1 to 1. Use 0 if no data." },
        label: { type: Type.STRING, enum: ["Positive", "Negative", "Neutral"] },
        confidence: { type: Type.NUMBER, description: "Confidence 0-1. Use 0 if no real data found." }
      },
      required: ["score", "label", "confidence"]
    },
    topics: {
      type: Type.ARRAY,
      description: "Topics extracted ONLY from actual search results. Return empty array if no data.",
      items: {
        type: Type.OBJECT,
        properties: {
          name: { type: Type.STRING },
          relevance: { type: Type.NUMBER }
        },
        required: ["name", "relevance"]
      }
    },
    emotions: {
      type: Type.ARRAY,
      description: "Emotions detected ONLY from actual content. Return empty array if no data.",
      items: { type: Type.STRING }
    },
    key_entities: {
      type: Type.ARRAY,
      description: "Entities extracted ONLY from search results. Return empty array if no data.",
      items: { type: Type.STRING }
    },
    deep_inference: {
      type: Type.ARRAY,
      description: "Inferences based ONLY on actual data. Return empty array if insufficient data.",
      items: {
        type: Type.OBJECT,
        properties: {
          title: { type: Type.STRING },
          description: { type: Type.STRING },
          type: { type: Type.STRING, enum: ["pattern", "anomaly", "prediction"] }
        },
        required: ["title", "description", "type"]
      }
    },
    actionable_advice: {
      type: Type.STRING,
      description: "Advice based ONLY on actual posts found. State 'Insufficient data for recommendations' if no real data."
    },
    posts: {
      type: Type.ARRAY,
      description: "CRITICAL: Include ONLY posts that are DIRECTLY QUOTED or EXPLICITLY MENTIONED in the search context. DO NOT INVENT, FABRICATE, OR HALLUCINATE any post content. If no posts are found in search results, return an EMPTY ARRAY. Never generate fake posts.",
      items: {
        type: Type.OBJECT,
        properties: {
          author: { type: Type.STRING, description: "The exact username/handle as found in search results. Do not invent usernames." },
          content: { type: Type.STRING, description: "EXACT text from search results ONLY. Do not paraphrase or invent content. Copy verbatim." },
          date: { type: Type.STRING, description: "ISO format YYYY-MM-DDTHH:mm:ss. Use only dates found in search results." },
          sentimentLabel: { type: Type.STRING, enum: ["Positive", "Negative", "Neutral"] },
          engagementScore: { type: Type.NUMBER, description: "Based on actual metrics if available, otherwise use 50 as default." },
          isPreferred: { type: Type.BOOLEAN },
          verified_from_source: { type: Type.BOOLEAN, description: "Set to true ONLY if this post content was directly found in search results." },
          mediaUrl: { type: Type.STRING, description: "URL for media ONLY if explicitly found in search grounding. Otherwise omit." },
          mediaType: { type: Type.STRING, enum: ["image", "video"] },
          url: { type: Type.STRING, description: "Direct link to the post ONLY if found in search results." }
        },
        required: ["author", "content", "date", "sentimentLabel", "engagementScore", "isPreferred", "verified_from_source"]
      }
    }
  },
  required: ["summary", "sentiment", "topics", "emotions", "key_entities", "deep_inference", "actionable_advice", "posts", "data_source_verified"]
};

/**
 * Helper to perform API calls with basic retry logic
 */
async function withRetry<T>(fn: () => Promise<T>, maxRetries = 2): Promise<T> {
  let lastError: any;
  for (let i = 0; i <= maxRetries; i++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (i < maxRetries) {
        // Exponential backoff
        await new Promise(r => setTimeout(r, 1000 * Math.pow(2, i)));
        console.warn(`Retrying API call (${i + 1}/${maxRetries})...`);
      }
    }
  }
  throw lastError;
}

export const analyzeSocialContent = async (text: string, platform: Platform, preferredAccounts: string[] = []): Promise<AnalysisResult> => {
  return withRetry(async () => {
    const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
    
    const prompt = `Analyze the following ${platform} content that was provided by the user.
    
    USER-PROVIDED CONTENT:
    """
    ${text}
    """
    
    Preferred accounts to highlight: ${preferredAccounts.join(',') || 'None specified'}
    
    CRITICAL RULES:
    1. ONLY analyze the content provided above - do not add, invent, or fabricate additional posts.
    2. Extract posts ONLY from the text provided - every post must be traceable to the input.
    3. Set data_source_verified to true since this is user-provided content.
    4. Set verified_from_source to true for all extracted posts since they come from user input.
    5. If the input text is empty or contains no actual posts, return empty posts array.
    `;
    
    const response = await ai.models.generateContent({
      model: "gemini-3-flash-preview",
      contents: prompt,
      config: {
        responseMimeType: "application/json",
        responseSchema: analysisSchema,
        temperature: 0,
      },
    });
    const data = JSON.parse(response.text || '{}');
    data.posts = (data.posts || []).map((p: any, i: number) => ({ ...p, id: `p-${Date.now()}-${i}` }));
    return data as AnalysisResult;
  });
};

export const crawlAndAnalyzeTopic = async (
  topic: string, 
  platform: Platform, 
  mode: AnalysisMode = 'crawl',
  preferredAccounts: string[] = []
): Promise<{ analysis: AnalysisResult, sources: string[] }> => {
  const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
  
  // SYNC TO 19-DEC-2025 (Simulated Environment)
  const now = new Date();
  const simulatedNow = new Date(2025, 11, 19, now.getHours(), now.getMinutes(), now.getSeconds());
  const simulatedISO = simulatedNow.toISOString();
  
  // Improved Handle Extraction
  let handle = topic;
  if (topic.includes('t.me/')) {
    const parts = topic.split('t.me/')[1].split('/');
    handle = parts[0]; // Get channel name even if a post ID is present
  } else if (topic.includes('reddit.com/r/')) {
    handle = topic.split('r/')[1].split('/')[0];
  } else {
    handle = topic.split('/').pop()?.replace('@', '') || topic;
  }

  let searchPrompt = '';
  const isDirectUrl = topic.startsWith('http');

  if (mode === 'fetch_posts' || isDirectUrl) {
    searchPrompt = `
      CRAWL TASK: Scrape latest public entries from ${platform}.
      SPECIFIC TARGET: "${topic}"
      CHANNEL/HANDLE: ${handle}
      TIME: Today is Dec 19, 2025.
      INSTRUCTIONS:
      1. If the input is a direct link (e.g., t.me/channel/123), prioritize finding the content of EXACTLY that post.
      2. If it's a channel link, find the top 5 most recent posts.
      3. SEARCH QUERY: "${topic}" OR site:t.me/s/${handle} OR site:reddit.com/r/${handle}
    `;
  } else {
    searchPrompt = `
      CRAWL TOPIC: "${topic}" on ${platform}.
      CONTEXT: Active trends as of Dec 19, 2025.
      SEARCH QUERY: "${topic}" ${platform} after:2025-12-15
    `;
  }

  let searchResponse;
  try {
    searchResponse = await withRetry(async () => {
      return await ai.models.generateContent({
        model: "gemini-3-pro-preview",
        contents: searchPrompt,
        config: { tools: [{ googleSearch: {} }] },
      });
    });
  } catch (err) {
    console.error("Search Grounding failed:", err);
    return {
      analysis: generateNoDataResponse(topic, platform),
      sources: ["ERROR: Search service unavailable"]
    };
  }

  const searchContext = searchResponse.text;
  const sources: string[] = (searchResponse.candidates?.[0]?.groundingMetadata?.groundingChunks || [])
    .map((c: any) => c.web?.uri)
    .filter((u: any): u is string => typeof u === 'string');

  const structPrompt = `
    SEARCH RESULTS FOR ${platform}:
    """
    ${searchContext}
    """
    
    TARGET URL/TOPIC: ${topic}
    
    TASK: Extract social media posts from the search results above.
    
    CRITICAL ANTI-HALLUCINATION RULES:
    1. ONLY include posts that are EXPLICITLY QUOTED or MENTIONED in the search results above.
    2. If you cannot find actual post content in the search results, return an EMPTY posts array.
    3. DO NOT invent, fabricate, or generate fictional post content.
    4. DO NOT create plausible-sounding posts that aren't in the search results.
    5. If the search results only mention a channel exists but don't show actual posts, set data_source_verified to false and leave posts empty.
    6. Copy post content VERBATIM from search results - do not paraphrase or enhance.
    7. Use only author names/handles that appear in the search results.
    8. For dates, only use dates mentioned in search results. If no date found, use "unknown" and I will filter it out.
    9. Set verified_from_source to true ONLY for posts with content directly from search results.
    10. If search results are empty or irrelevant, return: {"summary": "No relevant data found in search results", "data_source_verified": false, "posts": [], ...}
    
    VALIDATION:
    - Every post in your response MUST have a direct source in the search context above.
    - If you're uncertain whether content is real, DO NOT include it.
    - An empty response is better than a fabricated one.
  `;

  const structResponse = await withRetry(async () => {
    return await ai.models.generateContent({
      model: "gemini-3-flash-preview",
      contents: structPrompt,
      config: {
        responseMimeType: "application/json",
        responseSchema: analysisSchema,
        temperature: 0,
      },
    });
  });

  const data = JSON.parse(structResponse.text || '{}') as AnalysisResult;
  
  // Post-processing validation: Filter out unverified posts to prevent hallucination
  const verifiedPosts = (data.posts || []).filter((p: any) => {
    // Keep only posts marked as verified from source
    if (p.verified_from_source === false) return false;
    // Filter out posts with placeholder or suspicious content
    if (!p.content || p.content.length < 10) return false;
    if (p.content.toLowerCase().includes('no data') || p.content.toLowerCase().includes('not found')) return false;
    if (p.date === 'unknown' || !p.date) return false;
    return true;
  });
  
  data.posts = verifiedPosts.map((p: any, i: number) => ({ ...p, id: `c-${Date.now()}-${i}` }));
  
  // If no verified posts and data wasn't verified, mark it clearly
  if (data.posts.length === 0 && !(data as any).data_source_verified) {
    data.summary = `[NO VERIFIED DATA] ${data.summary || 'Could not retrieve verified content from search results.'}`;
  }

  return { analysis: data, sources: Array.from(new Set<string>(sources)) };
};

/**
 * Returns a clear "no data" response when search fails - NO SIMULATION OR FABRICATION
 */
function generateNoDataResponse(topic: string, platform: Platform): AnalysisResult {
  return {
    summary: `Unable to retrieve real-time data for "${topic}" on ${platform}. Search grounding failed or returned no results. Please try again or verify the URL/topic.`,
    data_source_verified: false,
    sentiment: { score: 0, label: 'Neutral', confidence: 0 },
    topics: [],
    emotions: [],
    key_entities: [],
    deep_inference: [{
      title: 'Data Unavailable',
      description: 'The search service could not retrieve live data. This could be due to rate limiting, network issues, or the target being inaccessible.',
      type: 'anomaly'
    }],
    actionable_advice: 'Please verify the URL or topic is correct and try again. If the issue persists, the target may be private or unavailable.',
    posts: []
  } as AnalysisResult;
}
