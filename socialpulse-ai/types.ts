
export enum Platform {
  REDDIT = 'Reddit',
  TELEGRAM = 'Telegram',
  YOUTUBE = 'YouTube',
  TWITTER = 'X (Twitter)',
  OTHER = 'General Web'
}

export interface SentimentData {
  score: number; // -1 to 1
  label: 'Positive' | 'Negative' | 'Neutral';
  confidence: number;
}

export interface Topic {
  name: string;
  relevance: number; // 0 to 100
}

export interface Insight {
  title: string;
  description: string;
  type: 'pattern' | 'anomaly' | 'prediction';
}

export interface SocialPost {
  id: string;
  author: string;
  content: string;
  date: string; // ISO YYYY-MM-DDTHH:mm:ss
  sentimentLabel: 'Positive' | 'Negative' | 'Neutral';
  engagementScore: number; // 0-100 normalized
  isPreferred: boolean;
  verified_from_source: boolean; // true if content was directly found in search results
  url?: string;
  mediaUrl?: string; // URL for image or thumbnail
  mediaType?: 'image' | 'video';
}

export interface AnalysisResult {
  summary: string;
  data_source_verified: boolean; // true if response is based on actual search results
  sentiment: SentimentData;
  topics: Topic[];
  emotions: string[];
  key_entities: string[];
  deep_inference: Insight[];
  actionable_advice: string;
  posts: SocialPost[];
}

export type AnalysisMode = 'analyze' | 'crawl' | 'fetch_posts';

export interface CrawlResult {
  source_title: string;
  source_url: string;
  snippet: string;
}

export interface MonitoredSource {
  id: string;
  name: string;
  url: string;
  platform: Platform;
  lastChecked?: string;
}
