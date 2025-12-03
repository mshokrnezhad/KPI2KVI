import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, Bot, Image as ImageIcon, Mic, MoreHorizontal } from 'lucide-react';

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
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
    setInputValue('');
    setHasStarted(true);
    setIsTyping(true);

    // Simulate AI response
    setTimeout(() => {
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        text: "This is a simulated AI response based on your input. In a real application, this would connect to an API.",
        sender: 'ai',
      };
      setMessages((prev) => [...prev, aiMsg]);
      setIsTyping(false);
    }, 1500);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="min-h-screen bg-[#212121] text-gray-100 font-sans flex flex-col overflow-hidden">
      {/* Header - only visible in chat mode or always? Usually top bar is always there or fades in */}
      <div className="absolute top-0 left-0 right-0 p-4 flex justify-between items-center z-10">
        <div className="flex items-center gap-2 text-lg font-semibold text-gray-300">
          <span>ChatGPT </span> 
          <span className="opacity-50">Clone</span>
        </div>
        <div className="flex gap-4">
             {/* User avatar placeholder */}
            <div className="w-8 h-8 bg-green-600 rounded-full flex items-center justify-center text-sm">U</div>
        </div>
      </div>

      <main className={`flex-1 flex flex-col relative ${hasStarted ? 'justify-between' : 'justify-center items-center'}`}>
        
        {/* Chat History */}
        {hasStarted && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex-1 overflow-y-auto w-full max-w-3xl mx-auto p-4 pt-20 scrollbar-hide"
          >
            {messages.map((msg) => (
              <div key={msg.id} className={`mb-6 flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`flex gap-4 max-w-[80%] ${msg.sender === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                   <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${msg.sender === 'user' ? 'bg-gray-600' : 'bg-green-500'}`}>
                      {msg.sender === 'user' ? 'U' : <Bot size={18} />}
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
                    <div className="w-8 h-8 rounded-full bg-green-500 flex-shrink-0 flex items-center justify-center">
                      <Bot size={18} />
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
          </motion.div>
        )}

        {/* Landing Center Content */}
        {!hasStarted && (
          <motion.div 
            className="flex flex-col items-center gap-8 max-w-2xl w-full px-4 -mt-20"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
          >
            <div className="w-16 h-16 bg-white rounded-full flex items-center justify-center mb-4 shadow-lg shadow-white/10">
               <Bot color="black" size={40} />
            </div>
            <h1 className="text-3xl font-semibold text-center mb-4">How can I help you today?</h1>
            
            {/* Suggestion Cards */}
            <div className="grid grid-cols-2 gap-4 w-full">
               {[
                 { title: "Create a personal webpage", desc: "for my band" },
                 { title: "Write a story", desc: "about a time traveling dinosaur" },
                 { title: "Explain quantum physics", desc: "to a 5 year old" },
                 { title: "Plan a trip", desc: "to Japan for 2 weeks" },
               ].map((card, i) => (
                 <button 
                    key={i} 
                    className="bg-[#2f2f2f] hover:bg-[#424242] text-left p-4 rounded-xl border border-transparent hover:border-gray-600 transition-colors"
                    onClick={() => { setInputValue(`${card.title} ${card.desc}`); }}
                 >
                    <div className="font-medium text-gray-200">{card.title}</div>
                    <div className="text-sm text-gray-400">{card.desc}</div>
                 </button>
               ))}
            </div>
          </motion.div>
        )}

        {/* Input Area - Shared Layout Animation */}
        <div className={`w-full p-4 ${hasStarted ? 'bg-[#212121]' : ''}`}>
          <motion.div 
            layoutId="input-container"
            className={`relative mx-auto bg-[#2f2f2f] rounded-3xl border border-gray-600 shadow-lg overflow-hidden ${hasStarted ? 'max-w-3xl' : 'max-w-2xl'}`}
            transition={{ type: "spring", bounce: 0, duration: 0.6 }}
          >
             <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Message ChatGPT..."
                className="w-full bg-transparent border-none outline-none text-white p-4 pr-12 resize-none max-h-52 min-h-[56px]"
                rows={1}
                style={{ height: 'auto', minHeight: '56px' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = 'auto';
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                }}
             />
             
             <div className="absolute bottom-3 left-4 flex gap-3 text-gray-400">
                <button className="hover:text-white transition-colors"><ImageIcon size={20} /></button>
             </div>

             <div className="absolute bottom-3 right-3">
                <button 
                  onClick={handleSendMessage}
                  disabled={!inputValue.trim()}
                  className={`p-2 rounded-full transition-colors ${inputValue.trim() ? 'bg-white text-black' : 'bg-[#676767] text-[#2f2f2f] cursor-not-allowed'}`}
                >
                  <ArrowUp size={20} />
                </button>
             </div>
          </motion.div>
          
          <div className="text-center mt-2 text-xs text-gray-500">
            ChatGPT can make mistakes. Check important info.
          </div>
        </div>

      </main>
    </div>
  );
}

export default App;
