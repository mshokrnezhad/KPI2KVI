import { useState, useRef, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp } from 'lucide-react';
import llmLogo from './assets/images/llm.png';

const images = import.meta.glob('./assets/images/services/*.png', { eager: true, import: 'default' });
const imageList = Object.values(images) as string[];

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000';

// 3D Graph types and constants
interface Point3D { x: number; y: number; z: number; img: string; id: number }
interface Edge { start: number; end: number }
interface ProjectedPoint extends Point3D { sx: number; sy: number; scale: number; zIndex: number }

const GRAPH_RADIUS = 160;
const PERSPECTIVE = 800;
const ROTATION_SPEED = 0.002;
const HORIZONTAL_STRETCH = 1.35;
const VERTICAL_SQUASH = 0.85;

// Generate initial graph structure
const generateGraph = (images: string[]) => {
  const nodes: Point3D[] = images.map((img, i) => {
    // Fibonnaci sphere distribution for even spread
    const k = i;
    const n = images.length;
    const phi = Math.acos(1 - 2 * (k + 0.5) / n);
    const theta = Math.PI * (1 + Math.sqrt(5)) * k;

    return {
      x: GRAPH_RADIUS * Math.sin(phi) * Math.cos(theta),
      y: GRAPH_RADIUS * Math.sin(phi) * Math.sin(theta),
      z: GRAPH_RADIUS * Math.cos(phi),
      img,
      id: i
    };
  });

  const edges: Edge[] = [];
  // Create a dense neighbor graph by connecting to multiple nearest nodes
  nodes.forEach((node, i) => {
    // Connect to the 4 nearest neighbors
    const distances = nodes
      .map((n, idx) => ({ idx, dist: Math.pow(n.x - node.x, 2) + Math.pow(n.y - node.y, 2) + Math.pow(n.z - node.z, 2) }))
      .filter(item => item.idx !== i)
      .sort((a, b) => a.dist - b.dist)
      .slice(0, 4);

    distances.forEach(d => {
      const edgeExists = edges.some(e => (e.start === i && e.end === d.idx) || (e.start === d.idx && e.end === i));
      if (!edgeExists) {
        edges.push({ start: i, end: d.idx });
      }
    });
  });

  return { nodes, edges };
};

const { nodes: initialNodes, edges: initialEdges } = generateGraph(imageList);

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'ai';
}

function App() {
  const [hasStarted, setHasStarted] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [healthStatus, setHealthStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 3D Animation State
  const [rotation, setRotation] = useState(0);
  const animationRef = useRef<number>(0);

  useEffect(() => {
    const animate = () => {
      setRotation(prev => (prev + ROTATION_SPEED) % (2 * Math.PI));
      animationRef.current = requestAnimationFrame(animate);
    };
    animationRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationRef.current);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const checkHealth = async () => {
      try {
        const resp = await fetch(`${BACKEND_URL}/api/health`);
        if (!resp.ok) throw new Error('health-check-failed');
        const data = await resp.json();
        if (!cancelled) {
          setHealthStatus(data.status === 'ok' ? 'ok' : 'error');
        }
      } catch (err) {
        if (!cancelled) {
          setHealthStatus('error');
        }
      }
    };
    checkHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  // Calculate projected positions
  const { projectedNodes, projectedEdges } = useMemo(() => {
    const projected: ProjectedPoint[] = initialNodes.map(node => {
      // Rotate around Y axis
      const cos = Math.cos(rotation);
      const sin = Math.sin(rotation);

      // Apply rotation
      const x = node.x * cos - node.z * sin;
      const z = node.x * sin + node.z * cos;
      const y = node.y; // No rotation around X/Z for now, or add a slight wobble: + Math.sin(rotation * 3 + node.id) * 10;

      const stretchedX = x * HORIZONTAL_STRETCH;
      const squashedY = y * VERTICAL_SQUASH;

      // Project to 2D
      // Camera is at z = PERSPECTIVE. Points are at z ~ [-R, R].
      // We shift z so it's relative to camera: z_cam = PERSPECTIVE + z
      // scale = PERSPECTIVE / z_cam
      // But standard formula for "center of screen is (0,0)" and "z goes into screen":
      // scale = focal_length / (focal_length + z)
      const scale = PERSPECTIVE / (PERSPECTIVE + z + 200);

      return {
        ...node,
        sx: stretchedX * scale, // Screen X (relative to center)
        sy: squashedY * scale, // Screen Y
        scale,
        zIndex: Math.floor(scale * 1000)
      };
    });

    return { projectedNodes: projected, projectedEdges: initialEdges };
  }, [rotation]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      text: inputValue,
      sender: 'user',
    };

    setMessages((prev) => [...prev, userMsg]);
    const messageText = inputValue;
    setInputValue('');
    setHasStarted(true);
    setIsTyping(true);

    try {
      // Call the backend API
      const response = await fetch(`${BACKEND_URL}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // Update session ID if this is the first message
      if (!sessionId && data.session_id) {
        setSessionId(data.session_id);
      }

      // Add AI response
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        text: data.reply,
        sender: 'ai',
      };
      setMessages((prev) => [...prev, aiMsg]);
      setIsTyping(false);
    } catch (error) {
      console.error('Error calling backend:', error);
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        text: "Sorry, I encountered an error connecting to the backend. Please check the console for details.",
        sender: 'ai',
      };
      setMessages((prev) => [...prev, errorMsg]);
      setIsTyping(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const pulseClass =
    healthStatus === 'ok'
      ? 'bg-green-400/70 shadow-[0_0_30px_rgba(74,222,128,0.6)]'
      : 'bg-red-400/70 shadow-[0_0_30px_rgba(248,113,113,0.6)]';

  return (
    <div className="min-h-screen bg-[#212121] text-gray-100 font-sans flex flex-col overflow-hidden">
      {/* Header - only visible in chat mode or always? Usually top bar is always there or fades in */}
      <div className="absolute top-0 left-0 right-0 p-4 flex justify-between items-center z-10">
        <div className="flex items-center gap-2 text-lg font-semibold text-gray-300">
          <span>ICTFICIAL </span>
        </div>
        <div className="flex gap-4">
          {/* User avatar placeholder */}
          <span className="opacity-50">KPI2KVI</span>
        </div>
      </div>

      <main className="flex-1 flex flex-col relative">
        <AnimatePresence mode="wait">
          {/* Chat History */}
          {hasStarted && (
            <motion.div
              key="chat-history"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex flex-col justify-between overflow-hidden"
            >
              <div className="flex-1 overflow-y-auto w-full max-w-3xl mx-auto p-4 pt-20 scrollbar-hide">
                {messages.map((msg) => (
                  <div key={msg.id} className={`mb-6 flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`flex gap-4 max-w-[80%] ${msg.sender === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                      <div
                        className={`w-8 h-8 flex-shrink-0 flex items-center justify-center ${msg.sender === 'user'
                          ? 'rounded-full bg-gray-600 text-white'
                          : 'relative'
                          }`}
                      >
                        {msg.sender === 'user'
                          ? 'U'
                          : (
                            <div className="relative w-full h-full flex items-center justify-center">
                              <img src={llmLogo} alt="LLM" className="relative w-full h-full object-contain" />
                            </div>
                          )}
                      </div>
                      <div className={`p-3 rounded-2xl ${msg.sender === 'user' ? 'bg-[#2f2f2f] text-white' : 'text-gray-100'}`}>
                        <p className="leading-relaxed whitespace-pre-wrap">{msg.text}</p>
                      </div>
                    </div>
                  </div>
                ))}
                {isTyping && (
                  <div className="flex justify-start mb-6">
                    <div className="flex gap-4 max-w-[80%]">
                      <div className="w-8 h-8 flex-shrink-0 flex items-center justify-center relative">
                        <img src={llmLogo} alt="LLM" className="relative w-full h-full object-contain" />
                      </div>
                      <div className="flex items-center">
                        <span className="animate-pulse">●</span>
                        <span className="animate-pulse delay-100">●</span>
                        <span className="animate-pulse delay-200">●</span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </motion.div>
          )}

          {/* Landing Center Content */}
          {!hasStarted && (
            <motion.div
              key="landing-content"
              className="absolute inset-0 flex flex-col items-center justify-center gap-6 max-w-4xl w-full mx-auto px-6"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
            >
              <div className="relative w-20 h-20 mb-4 flex items-center justify-center">
                <div className={`absolute inset-[-8px] rounded-full blur-2xl animate-throb ${pulseClass}`} />
                <img src={llmLogo} alt="LLM Logo" className="relative w-20 h-20 object-contain" />
              </div>
              <h1 className="text-3xl font-semibold text-center mb-4">To Evaluate Your Service!</h1>

              {/* Floating 3D Graph */}
              <div className="relative w-full max-w-4xl h-72 flex items-center justify-center mt-2 mb-4 px-4" style={{ perspective: '1000px' }}>

                {/* SVG Layer for Lines - Fixed large size centered */}
                <svg
                  className="absolute pointer-events-none"
                  style={{
                    width: '1000px',
                    height: '1000px',
                    left: '50%',
                    top: '50%',
                    transform: 'translate(-50%, -50%)',
                    overflow: 'visible'
                  }}
                >
                  {/* Center the coordinate system in the SVG */}
                  <g transform="translate(500, 500)">
                    {projectedEdges.map((edge, i) => {
                      const startNode = projectedNodes[edge.start];
                      const endNode = projectedNodes[edge.end];

                      // Calculate opacity and width based on average Z depth (scale)
                      const avgScale = (startNode.scale + endNode.scale) / 2;
                      const depthFactor = Math.max(0, Math.min(1, (avgScale - 0.15) / 0.85)); // normalize between back/front
                      const opacity = 0.2 + depthFactor * 0.8; // 0.2 (far) -> 1 (close)
                      const width = 1 + depthFactor * 8; // 1px (far) -> 9px (close)

                      return (
                        <line
                          key={`edge-${i}`}
                          x1={startNode.sx}
                          y1={startNode.sy}
                          x2={endNode.sx}
                          y2={endNode.sy}
                          stroke="rgba(100, 200, 255, 0.5)" // Cyan-ish, visible but not blinding white
                          strokeWidth={width}
                          strokeLinecap="round"
                          style={{ opacity, transition: 'opacity 0.1s' }} // Simple opacity transition
                        />
                      );
                    })}
                  </g>
                </svg>

                {/* Center container for Nodes (0,0) */}
                <div className="relative w-0 h-0">
                  {/* Nodes */}
                  {projectedNodes.map((node) => {
                    const size = 96 * node.scale;
                    return (
                      <motion.div
                        key={node.id}
                        className="absolute flex items-center justify-center"
                        style={{
                          left: 0,
                          top: 0,
                          x: node.sx,
                          y: node.sy,
                          zIndex: node.zIndex,
                          width: size,
                          height: size,
                          marginLeft: `-${size / 2}px`,
                          marginTop: `-${size / 2}px`,
                        }}
                      >
                        <motion.img
                          src={node.img}
                          alt="node"
                          className="w-full h-full object-contain"
                          initial={{ scale: 0, opacity: 0 }}
                          animate={{
                            scale: node.scale,
                            opacity: Math.max(0.3, Math.min(1, node.scale * 1.5))
                          }}
                        />
                      </motion.div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Input Area - Shared Layout Animation */}
        <div className="absolute bottom-0 left-0 right-0 w-full p-4">
          <motion.div
            layoutId="input-container"
            className={`relative mx-auto bg-[#2f2f2f] rounded-3xl border border-gray-600 shadow-lg overflow-hidden ${hasStarted ? 'max-w-3xl' : 'max-w-2xl'}`}
            transition={{ type: "spring", bounce: 0, duration: 0.6 }}
          >
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                healthStatus === 'ok'
                  ? "Start by describing your service..."
                  : healthStatus === 'loading'
                    ? "Connecting to backend..."
                    : "Backend unavailable. Please check connection."
              }
              disabled={healthStatus !== 'ok'}
              className={`w-full bg-transparent border-none outline-none text-white p-4 pr-12 resize-none max-h-52 min-h-[56px] ${healthStatus !== 'ok' ? 'opacity-50 cursor-not-allowed' : ''}`}
              rows={1}
              style={{ height: 'auto', minHeight: '56px' }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = 'auto';
                target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
              }}
            />
            <div className="absolute bottom-3 right-3">
              <button
                onClick={handleSendMessage}
                disabled={!inputValue.trim() || healthStatus !== 'ok'}
                className={`p-2 rounded-full transition-colors ${inputValue.trim() && healthStatus === 'ok' ? 'bg-white text-black' : 'bg-[#676767] text-[#2f2f2f] cursor-not-allowed'}`}
              >
                <ArrowUp size={20} />
              </button>
            </div>
          </motion.div>

          <div className="text-center mt-2 text-xs text-gray-500">
            We might make mistakes. Check important information.
          </div>
        </div>

      </main>
    </div>
  );
}

export default App;
