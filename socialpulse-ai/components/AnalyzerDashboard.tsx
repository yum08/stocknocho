
import React, { useState, useMemo, useEffect } from 'react';
import { AnalysisResult, Topic, Insight, SocialPost, AnalysisMode } from '../types';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';

interface Props {
  data: AnalysisResult;
  sources?: string[];
  mode?: AnalysisMode;
}

const SentimentGauge = ({ score }: { score: number }) => {
  const percentage = ((score + 1) / 2) * 100;
  const chartData = [
    { name: 'Positive', value: percentage },
    { name: 'Negative', value: 100 - percentage },
  ];

  return (
    <div className="w-full relative flex items-center justify-center" style={{ height: '192px', minWidth: 0 }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            startAngle={180}
            endAngle={0}
            innerRadius={60}
            outerRadius={80}
            paddingAngle={5}
            dataKey="value"
            stroke="none"
          >
            <Cell key="pos" fill={percentage > 50 ? '#10B981' : '#EF4444'} />
            <Cell key="neg" fill="#374151" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute bottom-10 text-center">
        <div className="text-3xl font-bold text-white">{score.toFixed(2)}</div>
        <div className="text-xs text-gray-400">Sentiment Score</div>
      </div>
    </div>
  );
};

const TopicBarChart = ({ topics }: { topics: Topic[] }) => {
  return (
    <div className="w-full overflow-hidden" style={{ height: '200px', minWidth: 0 }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
        <BarChart data={topics} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
          <XAxis type="number" hide />
          <YAxis dataKey="name" type="category" width={100} tick={{ fill: '#9CA3AF', fontSize: 12 }} />
          <Tooltip 
            contentStyle={{ backgroundColor: '#1F2937', borderColor: '#374151', color: '#fff' }}
            itemStyle={{ color: '#fff' }}
            cursor={{fill: '#374151', opacity: 0.4}}
          />
          <Bar dataKey="relevance" fill="#6366F1" radius={[0, 4, 4, 0]} barSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

const InsightCard: React.FC<{ insight: Insight }> = ({ insight }) => {
  const getIcon = (type: string) => {
    switch (type) {
      case 'pattern': return '🔍';
      case 'anomaly': return '⚠️';
      case 'prediction': return '🔮';
      default: return '💡';
    }
  };

  return (
    <div className="bg-gray-800/50 border border-gray-700 p-4 rounded-lg hover:border-indigo-500/50 transition-colors">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">{getIcon(insight.type)}</span>
        <h4 className="font-semibold text-gray-200 capitalize">{insight.title}</h4>
      </div>
      <p className="text-sm text-gray-400 leading-relaxed">{insight.description}</p>
    </div>
  );
};

const PostCard: React.FC<{ post: SocialPost }> = ({ post }) => {
  const [timeInfo, setTimeInfo] = useState({ formatted: '', isFresh: false, isLive: false });

  useEffect(() => {
    const updateTime = () => {
      try {
        const d = new Date(post.date);
        if (isNaN(d.getTime())) {
          setTimeInfo({ formatted: post.date, isFresh: false, isLive: false });
          return;
        }

        const now = new Date();
        const nowInSim = new Date(2025, 11, 19, now.getHours(), now.getMinutes(), now.getSeconds());
        const diffMs = nowInSim.getTime() - d.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        
        let relative = '';
        if (diffMins < 0) relative = 'Future Log'; 
        else if (diffMins < 1) relative = 'Just Now';
        else if (diffMins < 60) relative = `${diffMins}m ago`;
        else if (diffMins < 1440) relative = `${Math.floor(diffMins / 60)}h ago`;
        else relative = `${Math.floor(diffMins / 1440)}d ago`;

        const options: Intl.DateTimeFormatOptions = {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: true,
          timeZoneName: 'short'
        };
        const localTime = d.toLocaleTimeString([], options);

        setTimeInfo({ 
          formatted: `${localTime} (${relative})`, 
          isFresh: diffMins < 45,
          isLive: diffMins < 5
        });
      } catch (e) {
        setTimeInfo({ formatted: post.date, isFresh: false, isLive: false });
      }
    };

    updateTime();
    const interval = setInterval(updateTime, 10000);
    return () => clearInterval(interval);
  }, [post.date]);

  return (
    <div className={`p-5 rounded-2xl border transition-all ${post.isPreferred ? 'bg-indigo-900/10 border-indigo-500/40 shadow-lg shadow-indigo-500/5' : 'bg-gray-900/60 border-gray-800 hover:border-gray-600'}`}>
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center font-bold text-gray-400 border border-gray-700">
            {post.author[1]?.toUpperCase() || '@'}
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-bold text-gray-200 truncate max-w-[150px] leading-tight">{post.author}</span>
              {timeInfo.isLive && (
                <span className="bg-rose-600 text-[8px] px-1.5 py-0.5 rounded text-white font-black animate-pulse">LIVE</span>
              )}
            </div>
            <span className={`text-[10px] font-mono ${timeInfo.isFresh ? 'text-emerald-400' : 'text-gray-500'}`}>
              {timeInfo.formatted}
            </span>
          </div>
        </div>
        <div className={`text-[9px] px-2 py-1 rounded border uppercase font-black tracking-widest ${
          post.sentimentLabel === 'Positive' ? 'border-emerald-800/50 bg-emerald-900/20 text-emerald-400' :
          post.sentimentLabel === 'Negative' ? 'border-rose-800/50 bg-rose-900/20 text-rose-400' :
          'border-gray-700 bg-gray-800/50 text-gray-400'
        }`}>
          {post.sentimentLabel}
        </div>
      </div>
      
      {post.mediaUrl && (
        <div className="mb-4 rounded-xl overflow-hidden border border-gray-800 bg-gray-950 aspect-video relative group cursor-zoom-in">
           <img 
            src={post.mediaUrl} 
            alt="Captured media" 
            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
            onError={(e) => {
              (e.target as HTMLImageElement).src = 'https://images.unsplash.com/photo-1635805737707-575885ab0820?auto=format&fit=crop&q=80&w=1000';
            }}
           />
           <div className="absolute bottom-2 right-2 bg-black/60 backdrop-blur-md px-2 py-1 rounded text-[10px] text-white/80 border border-white/10">
              Media Attached
           </div>
        </div>
      )}

      <p className="text-sm text-gray-300 mb-5 whitespace-pre-wrap leading-relaxed selection:bg-indigo-500/30">
        {post.content}
      </p>
      
      <div className="flex items-center justify-between text-[10px] text-gray-500 pt-3 border-t border-gray-800/50">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 bg-gray-950 px-2 py-1 rounded border border-gray-800">
            <svg className="w-3 h-3 text-indigo-500" fill="currentColor" viewBox="0 0 20 20"><path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 10.333a2 2 0 00-.8 0z" /></svg>
            Score: {post.engagementScore}
          </div>
          {post.verified_from_source ? (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
              <span className="text-emerald-400">Verified from Source</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
              <span className="text-amber-400">Unverified</span>
            </div>
          )}
        </div>
        {post.url && (
          <a href={post.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-indigo-400 hover:text-indigo-300 font-bold">
            Original 
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
          </a>
        )}
      </div>
    </div>
  );
};

export const AnalyzerDashboard: React.FC<Props> = ({ data, sources, mode }) => {
  const [filterText, setFilterText] = useState('');
  const [filterSentiment, setFilterSentiment] = useState<'All' | 'Positive' | 'Negative' | 'Neutral'>('All');
  const [sortBy, setSortBy] = useState<'Date' | 'Engagement' | 'Relevance'>('Date');

  useEffect(() => {
    if (mode === 'fetch_posts') setSortBy('Date');
    else setSortBy('Relevance');
  }, [mode]);

  const filteredAndSortedPosts = useMemo(() => {
    let posts = [...(data.posts || [])];

    if (filterText) {
      const lowerText = filterText.toLowerCase();
      posts = posts.filter(p => 
        p.content.toLowerCase().includes(lowerText) || 
        p.author.toLowerCase().includes(lowerText)
      );
    }

    if (filterSentiment !== 'All') {
      posts = posts.filter(p => p.sentimentLabel === filterSentiment);
    }

    posts.sort((a, b) => {
      if (sortBy === 'Date') return new Date(b.date).getTime() - new Date(a.date).getTime();
      if (sortBy === 'Engagement') return b.engagementScore - a.engagementScore;
      const scoreA = a.engagementScore + (a.isPreferred ? 50 : 0);
      const scoreB = b.engagementScore + (b.isPreferred ? 50 : 0);
      return scoreB - scoreA;
    });

    return posts;
  }, [data.posts, filterText, filterSentiment, sortBy]);

  return (
    <div className="animate-fade-in space-y-8">
      {/* Data Verification Warning Banner */}
      {!data.data_source_verified && (
        <div className="bg-amber-900/20 border border-amber-500/50 rounded-2xl p-4 flex items-center gap-3">
          <svg className="w-6 h-6 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <div className="text-amber-400 font-bold text-sm">Unverified Data Warning</div>
            <div className="text-amber-300/70 text-xs">The search results could not be verified. Data shown may be incomplete or unavailable. Please verify the source URL and try again.</div>
          </div>
        </div>
      )}
      
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
         <div className="bg-gray-900 border border-gray-800 p-4 rounded-2xl shadow-inner bg-gradient-to-br from-gray-900 to-gray-950">
           <div className="text-[10px] text-gray-500 uppercase tracking-widest font-black mb-1 opacity-70">Sentiment Orbit</div>
           <div className={`text-2xl font-black ${
             data.sentiment.label === 'Positive' ? 'text-emerald-400' :
             data.sentiment.label === 'Negative' ? 'text-rose-400' : 'text-amber-400'
           }`}>{data.sentiment.label}</div>
           <div className="text-[10px] text-gray-600 mt-1">Grounding Confidence: {(data.sentiment.confidence * 100).toFixed(0)}%</div>
         </div>
         <div className="bg-gray-900 border border-gray-800 p-4 rounded-2xl shadow-inner bg-gradient-to-br from-gray-900 to-gray-950">
           <div className="text-[10px] text-gray-500 uppercase tracking-widest font-black mb-1 opacity-70">Emotional Spectrum</div>
           <div className="flex flex-wrap gap-1 mt-1">
             {data.emotions.slice(0, 3).map(e => (
               <span key={e} className="bg-indigo-900/30 text-indigo-300 text-[9px] px-2 py-0.5 rounded-full border border-indigo-500/20 font-bold uppercase">{e}</span>
             ))}
           </div>
         </div>
         <div className="bg-gray-900 border border-gray-800 p-4 rounded-2xl shadow-inner bg-gradient-to-br from-gray-900 to-gray-950">
           <div className="text-[10px] text-gray-500 uppercase tracking-widest font-black mb-1 opacity-70">Synced Signals</div>
           <div className="text-2xl font-black text-white">{data.posts.length}</div>
           <div className="text-[10px] text-gray-600 mt-1">Latest: 19-DEC-2025</div>
         </div>
         <div className="bg-gray-900 border border-gray-800 p-4 rounded-2xl shadow-inner bg-gradient-to-br from-gray-900 to-gray-950">
           <div className="text-[10px] text-gray-500 uppercase tracking-widest font-black mb-1 opacity-70">Discovery Trace</div>
           <div className="text-xl font-bold text-indigo-400 truncate">{sources?.[0]?.replace(/https?:\/\/(www\.)?/, '') || 'Native Stream'}</div>
           <div className="text-[10px] text-gray-600 mt-1">{sources?.length || 0} unique sources scanned</div>
         </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-3xl p-7 shadow-2xl relative overflow-hidden">
            <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
               <svg className="w-24 h-24 text-indigo-500" fill="currentColor" viewBox="0 0 20 20"><path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zM8 7a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zM14 4a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z"></path></svg>
            </div>
            <h3 className="text-xl font-black text-white mb-5 flex items-center gap-3">
              <span className="w-2 h-8 bg-indigo-600 rounded-full shadow-[0_0_15px_rgba(79,70,229,0.5)]"></span>
              Intelligence Abstract
            </h3>
            <div className="text-sm text-gray-400 leading-relaxed mb-8 bg-black/30 p-4 rounded-2xl border border-gray-800/50 italic">"{data.summary}"</div>
            <SentimentGauge score={data.sentiment.score} />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-3xl p-7 shadow-2xl">
            <h3 className="text-xl font-black text-white mb-6">Inferred Trajectories</h3>
            <div className="space-y-4">
              {data.deep_inference.map((insight, idx) => (
                <InsightCard key={idx} insight={insight} />
              ))}
            </div>
          </div>

          <div className="bg-indigo-950/20 border border-indigo-500/30 rounded-3xl p-7 shadow-xl">
             <h3 className="text-xl font-black text-indigo-300 mb-3 uppercase tracking-tighter">Strategic Advice</h3>
             <p className="text-sm text-gray-400 leading-relaxed">{data.actionable_advice}</p>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-3xl p-7 shadow-2xl">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
              <div className="flex items-center gap-4">
                 <div className="w-4 h-4 bg-emerald-500 rounded-full animate-pulse shadow-[0_0_20px_rgba(16,185,129,0.6)]"></div>
                 <h3 className="text-2xl font-black text-white tracking-tighter">
                   {mode === 'fetch_posts' ? 'Direct Pulse Stream' : 'Grounding Extract'}
                 </h3>
              </div>
              <div className="bg-black/40 px-4 py-1.5 rounded-full border border-gray-800 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
                <span className="text-[11px] font-black text-gray-400 uppercase tracking-widest">PROBED AT 19-DEC-2025</span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 bg-black/40 p-5 rounded-2xl border border-gray-800/50">
               <div className="relative">
                 <input 
                  type="text" 
                  value={filterText}
                  onChange={(e) => setFilterText(e.target.value)}
                  placeholder="Deep scan..."
                  className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-xs text-white outline-none focus:border-indigo-500 transition-all"
                 />
               </div>
               <div>
                  <select 
                    value={filterSentiment}
                    onChange={(e) => setFilterSentiment(e.target.value as any)}
                    className="w-full bg-gray-900 border border-gray-700 rounded-xl px-3 py-2.5 text-xs text-white outline-none focus:border-indigo-500 transition-all"
                  >
                    <option value="All">All Polarities</option>
                    <option value="Positive">Optimistic</option>
                    <option value="Negative">Critical</option>
                    <option value="Neutral">Neutral</option>
                  </select>
               </div>
               <div>
                  <select 
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as any)}
                    className="w-full bg-gray-900 border border-gray-700 rounded-xl px-3 py-2.5 text-xs text-white outline-none focus:border-indigo-500 transition-all"
                  >
                    <option value="Date">Timeline Chrono</option>
                    <option value="Engagement">Engagement Heat</option>
                    <option value="Relevance">AI Relevance</option>
                  </select>
               </div>
            </div>

            <div className="space-y-6 max-h-[900px] overflow-y-auto pr-3 custom-scrollbar">
              {filteredAndSortedPosts.length > 0 ? (
                filteredAndSortedPosts.map((post) => (
                  <PostCard key={post.id} post={post} />
                ))
              ) : (
                <div className="text-center py-40 text-gray-700">
                  <svg className="w-16 h-16 mx-auto mb-6 opacity-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                  <p className="text-lg font-black uppercase tracking-widest">No Signals Captured</p>
                </div>
              )}
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-3xl p-7 shadow-2xl">
             <h3 className="text-xl font-black text-white mb-6">Semantic Relevance</h3>
             <TopicBarChart topics={data.topics} />
          </div>
        </div>
      </div>
    </div>
  );
};
