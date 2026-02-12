
import React, { useState, useEffect } from 'react';
import { Platform, AnalysisResult, AnalysisMode, MonitoredSource } from './types';
import { PLATFORM_ICONS, APP_NAME } from './constants';
import { analyzeSocialContent, crawlAndAnalyzeTopic } from './services/geminiService';
import { AnalyzerDashboard } from './components/AnalyzerDashboard';

const App: React.FC = () => {
  const [mode, setMode] = useState<AnalysisMode>('analyze');
  const [platform, setPlatform] = useState<Platform>(Platform.REDDIT);
  
  // Processing states (moved up to avoid "used before declaration" errors)
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Input states
  const [inputText, setInputText] = useState('');
  const [topic, setTopic] = useState('');
  
  // Simulated Clock State
  const [serverTime, setServerTime] = useState('');

  // Loading status messages
  const [loadingStatus, setLoadingStatus] = useState('Initializing Scraper...');
  const loadingMessages = [
    'Establishing secure proxy connection...',
    'Bypassing rate limiters...',
    'Injecting crawler scripts...',
    'Scanning platform indexes...',
    'Parsing HTML structure...',
    'Extracting metadata...',
    'Analyzing sentiment vectors...',
    'Finalizing data reconstruction...'
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      const sim = new Date(2025, 11, 19, now.getHours(), now.getMinutes(), now.getSeconds());
      setServerTime(sim.toLocaleTimeString('en-IN', { 
        day: '2-digit', 
        month: 'short', 
        year: 'numeric',
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit' 
      }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Use state variables only after their declaration
  useEffect(() => {
    let msgIndex = 0;
    let interval: any;
    if (loading) {
      interval = setInterval(() => {
        setLoadingStatus(loadingMessages[msgIndex % loadingMessages.length]);
        msgIndex++;
      }, 2500);
    }
    return () => clearInterval(interval);
  }, [loading]);

  // Preferred Accounts state
  const [preferredAccounts, setPreferredAccounts] = useState<string[]>([]);
  const [newAccountInput, setNewAccountInput] = useState('');

  // Monitoring State
  const [monitoredSources, setMonitoredSources] = useState<MonitoredSource[]>([
    { id: 'default-1', name: 'DGP India', url: 'https://t.me/DGPIndia', platform: Platform.TELEGRAM },
    { id: 'default-2', name: 'OpenAI Twitter', url: 'https://twitter.com/OpenAI', platform: Platform.TWITTER }
  ]);

  const handleAddAccount = () => {
    if (newAccountInput.trim() && !preferredAccounts.includes(newAccountInput.trim())) {
      setPreferredAccounts([...preferredAccounts, newAccountInput.trim()]);
      setNewAccountInput('');
    }
  };

  const handleRemoveAccount = (account: string) => {
    setPreferredAccounts(preferredAccounts.filter(a => a !== account));
  };

  const runAnalysis = async (
    targetText: string, 
    targetMode: AnalysisMode, 
    targetPlatform: Platform, 
    targetAccounts: string[]
  ) => {
    if (targetMode === 'analyze' && !targetText.trim()) {
      setError("Please paste some content to analyze.");
      return;
    }
    if ((targetMode === 'crawl' || targetMode === 'fetch_posts') && !targetText.trim()) {
      setError("Please enter a topic or URL.");
      return;
    }

    setLoading(true);
    setLoadingStatus('Initializing Scraper...');
    setError(null);
    setResult(null);
    setSources([]);

    try {
      if (targetMode === 'analyze') {
        const data = await analyzeSocialContent(targetText, targetPlatform, targetAccounts);
        setResult(data);
      } else {
        const { analysis, sources: foundSources } = await crawlAndAnalyzeTopic(targetText, targetPlatform, targetMode, targetAccounts);
        setResult(analysis);
        setSources(foundSources);
      }
    } catch (err: any) {
      console.error(err);
      setError(`Extraction encountered an issue: ${err.message || 'The network proxy is currently unstable. Please try again.'}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyzeClick = () => {
    if (mode === 'analyze') {
      runAnalysis(inputText, mode, platform, preferredAccounts);
    } else {
      runAnalysis(topic, mode, platform, preferredAccounts);
    }
  };

  const handleAddToMonitor = () => {
    if ((mode === 'crawl' || mode === 'fetch_posts') && topic.trim()) {
      const exists = monitoredSources.find(s => s.url === topic.trim());
      if (exists) return;

      const newSource: MonitoredSource = {
        id: Date.now().toString(),
        name: topic.includes('http') ? new URL(topic).pathname.slice(1) || 'Web Page' : topic,
        url: topic,
        platform: platform
      };
      setMonitoredSources([...monitoredSources, newSource]);
    }
  };

  const handleRemoveMonitor = (id: string) => {
    setMonitoredSources(monitoredSources.filter(s => s.id !== id));
  };

  const handleCheckSource = (source: MonitoredSource) => {
    const isDirectChannel = source.url.includes('t.me') || source.url.includes('twitter.com');
    const targetMode: AnalysisMode = isDirectChannel ? 'fetch_posts' : 'crawl';
    
    setMode(targetMode);
    setTopic(source.url);
    setPlatform(source.platform);
    
    runAnalysis(source.url, targetMode, source.platform, preferredAccounts);
    
    const updated = monitoredSources.map(s => s.id === source.id ? { ...s, lastChecked: new Date().toLocaleTimeString() } : s);
    setMonitoredSources(updated);
  };

  const handleMockFill = () => {
    if (mode === 'analyze') {
      setInputText(`[Breaking]: The President Bhawan has officially replaced all British-era portraits in the main hall with paintings of Param Veer Chakra awardees today, Dec 19, 2025.
      @IndianNews: Historical shift at Rashtrapati Bhavan.
      @CitizenX: Finally, our own heroes are getting the spotlight.`);
      setPreferredAccounts(['IndianNews']);
      setPlatform(Platform.TELEGRAM);
    } else if (mode === 'fetch_posts') {
      setTopic("https://t.me/DGPIndia");
      setPlatform(Platform.TELEGRAM);
      setPreferredAccounts(['DGPIndia']);
    } else {
      if (platform === Platform.YOUTUBE) {
        setTopic("Rashtrapati Bhavan Ceremony 2025"); 
        setPreferredAccounts(['DDNews']);
      } else {
        setTopic("President Bhawan British Rulers replacement");
        setPlatform(Platform.TWITTER);
      }
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-sans selection:bg-indigo-500 selection:text-white">
      
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-indigo-600 p-2 rounded-lg shadow-lg shadow-indigo-500/20">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400 leading-none">
                {APP_NAME}
              </h1>
              <div className="flex items-center gap-2 mt-1">
                 <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                 <span className="text-[10px] text-gray-500 font-mono uppercase tracking-widest">Server Time: {serverTime}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
             <div className="hidden md:flex items-center gap-2 px-3 py-1 bg-gray-800/50 rounded-full border border-gray-700">
                <span className="text-[10px] font-bold text-indigo-400 uppercase">Probing Pulse 2025</span>
             </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <section className="bg-gray-900 rounded-2xl border border-gray-800 p-6 mb-8 shadow-xl">
          <div className="flex flex-col md:flex-row gap-6">
            <div className="w-full md:w-1/3 space-y-6">
              <div>
                <label className="text-sm font-medium text-gray-400 mb-2 block">Operation Mode</label>
                <div className="flex bg-gray-950 p-1 rounded-lg border border-gray-800">
                  <button
                    onClick={() => setMode('analyze')}
                    className={`flex-1 py-2 px-2 rounded-md text-[13px] font-medium transition-all ${
                      mode === 'analyze' ? 'bg-indigo-600 text-white shadow-lg' : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Raw Analysis
                  </button>
                  <button
                    onClick={() => setMode('crawl')}
                    className={`flex-1 py-2 px-2 rounded-md text-[13px] font-medium transition-all ${
                      mode === 'crawl' ? 'bg-indigo-600 text-white shadow-lg' : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Topic Crawler
                  </button>
                  <button
                    onClick={() => setMode('fetch_posts')}
                    className={`flex-1 py-2 px-2 rounded-md text-[13px] font-medium transition-all ${
                      mode === 'fetch_posts' ? 'bg-indigo-600 text-white shadow-lg' : 'text-gray-400 hover:text-white'
                    }`}
                  >
                    Fetch Posts
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-2 h-8">
                  {mode === 'analyze' ? 'Analyze past content with 2025 context.' : mode === 'crawl' ? 'Discover trending topics for Dec 19, 2025.' : 'Retrieve real-time channel updates from today.'}
                </p>
              </div>

              <div>
                <label className="text-sm font-medium text-gray-400 mb-2 block">Target Platform</label>
                <div className="grid grid-cols-3 gap-2">
                  {Object.values(Platform).map((p) => (
                    <button
                      key={p}
                      onClick={() => setPlatform(p)}
                      className={`flex flex-col items-center justify-center p-2 rounded-lg border transition-all ${
                        platform === p ? 'bg-indigo-900/40 border-indigo-500 text-indigo-300' : 'bg-gray-950 border-gray-800 text-gray-500 hover:border-gray-600 hover:text-gray-300'
                      }`}
                    >
                      <svg className="w-5 h-5 mb-1 fill-current" viewBox="0 0 24 24">
                        <path d={PLATFORM_ICONS[p]} />
                      </svg>
                      <span className="text-[10px] truncate w-full text-center">{p}</span>
                    </button>
                  ))}
                </div>
              </div>

               <div>
                <label className="text-sm font-medium text-gray-400 mb-2 block">Preferred Accounts</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={newAccountInput}
                    onChange={(e) => setNewAccountInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddAccount()}
                    placeholder="Username..."
                    className="flex-1 bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-300 focus:ring-1 focus:ring-indigo-500 outline-none"
                  />
                  <button onClick={handleAddAccount} className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2 rounded-lg text-sm transition-colors">Add</button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {preferredAccounts.length === 0 && <span className="text-xs text-gray-600 italic">No specific accounts tracked</span>}
                  {preferredAccounts.map((account) => (
                    <span key={account} className="inline-flex items-center gap-1 bg-indigo-900/40 border border-indigo-500/30 text-indigo-300 text-xs px-2 py-1 rounded-full">
                      {account}
                      <button onClick={() => handleRemoveAccount(account)} className="hover:text-white">&times;</button>
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="w-full md:w-2/3 flex flex-col">
              {(mode === 'crawl' || mode === 'fetch_posts') && (
                <div className="mb-6">
                   <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                     <svg className="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>
                     Active Monitoring
                   </h3>
                   <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {monitoredSources.map(source => (
                        <div key={source.id} className="bg-gray-950 border border-gray-800 rounded-lg p-3 hover:border-gray-600 transition-colors flex justify-between items-center group">
                           <div className="flex items-center gap-3 overflow-hidden">
                              <div className="bg-gray-900 p-2 rounded shrink-0">
                                 <svg className="w-5 h-5 text-gray-400 fill-current" viewBox="0 0 24 24"><path d={PLATFORM_ICONS[source.platform]} /></svg>
                              </div>
                              <div className="min-w-0">
                                <h4 className="text-sm font-medium text-gray-200 truncate">{source.name}</h4>
                                <p className="text-[10px] text-gray-500 truncate">{source.lastChecked ? `Checked: ${source.lastChecked}` : 'Idle'}</p>
                              </div>
                           </div>
                           <div className="flex items-center gap-2">
                              <button onClick={() => handleCheckSource(source)} className="bg-indigo-900/50 hover:bg-indigo-700 text-indigo-300 hover:text-white text-xs px-2 py-1.5 rounded transition-colors">Sync</button>
                              <button onClick={() => handleRemoveMonitor(source.id)} className="text-gray-600 hover:text-red-400 p-1 opacity-0 group-hover:opacity-100 transition-opacity">&times;</button>
                           </div>
                        </div>
                      ))}
                   </div>
                </div>
              )}

              <div className="flex justify-between items-center mb-2">
                <label className="text-sm font-medium text-gray-400">
                  {mode === 'analyze' ? 'Input Content' : mode === 'crawl' ? 'Topic' : 'Handle / URL'}
                </label>
                <button onClick={handleMockFill} className="text-xs text-indigo-400 hover:text-indigo-300 hover:underline">Load Dec 19 Breaking Data</button>
              </div>
              
              {mode === 'analyze' ? (
                <textarea
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Paste Dec 19 content here..."
                  className="w-full h-40 bg-gray-950 border border-gray-800 rounded-xl p-4 text-gray-300 focus:ring-2 focus:ring-indigo-500 outline-none resize-none font-mono text-sm"
                />
              ) : (
                <div className="relative group">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <svg className={`h-5 w-5 ${platform === Platform.YOUTUBE ? 'text-red-500' : 'text-gray-500'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                  </div>
                  <input
                    type="text"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="Enter topic or URL..."
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl py-3 pl-10 pr-24 text-gray-300 focus:ring-2 focus:ring-indigo-500 outline-none h-12"
                  />
                  {topic.trim() && (
                    <button onClick={handleAddToMonitor} className="absolute right-2 top-2 bottom-2 bg-gray-800 hover:bg-gray-700 text-xs px-3 rounded-lg text-gray-300 border border-gray-700">+ Monitor</button>
                  )}
                  <div className="mt-4 p-4 bg-blue-900/20 border border-blue-900/50 rounded-lg">
                    <p className="text-xs text-blue-300 flex items-start gap-2">
                      <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                      Crawling Engine active. Synced to Grounding Date: Dec 19, 2025.
                    </p>
                  </div>
                </div>
              )}

              <div className="mt-4 flex justify-end">
                <button
                  onClick={handleAnalyzeClick}
                  disabled={loading}
                  className={`px-8 py-3 rounded-xl font-bold text-white shadow-lg transition-all transform hover:scale-105 active:scale-95 flex items-center gap-2 ${
                    loading ? 'bg-indigo-800 cursor-not-allowed' : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500'
                  }`}
                >
                  {loading ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      {loadingStatus}
                    </>
                  ) : mode === 'fetch_posts' ? 'Fetch Latest Feed' : 'Start Crawler'}
                </button>
              </div>
            </div>
          </div>
        </section>

        {error && (
          <div className="bg-red-900/20 border border-red-500/50 text-red-200 p-4 rounded-xl mb-8 flex items-center gap-3 animate-fade-in">
            <svg className="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            <div className="flex-1">
              <p className="font-bold">Scraper Error</p>
              <p className="text-sm opacity-80">{error}</p>
            </div>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-white">&times;</button>
          </div>
        )}

        {result && <AnalyzerDashboard data={result} sources={sources} mode={mode} />}

        {!result && !loading && !error && (
          <div className="text-center py-20 opacity-50">
            <h2 className="text-2xl font-bold text-gray-300">Live Pulse Ready</h2>
            <p className="text-gray-500 mt-2 max-w-md mx-auto">Extraction engine is currently synced to the Dec 19, 2025 event cycle.</p>
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
