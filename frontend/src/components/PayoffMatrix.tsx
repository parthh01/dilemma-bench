import { Gavel, ShieldCheck, User, UserCircle, Lock} from "lucide-react";





export default function PayoffMatrix() {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="rounded-xl border border-gray-800 bg-gray-900 text-white shadow-sm overflow-hidden">
        <div className="grid grid-cols-3 border-t border-gray-800">
          {/* Top-left legend */}
          <div className="bg-gray-800 p-3 text-left text-xs font-medium text-gray-300 flex items-center">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1 text-gray-300"><User size={14} /> You</span>
              <span className="flex items-center gap-1 text-gray-300"><UserCircle size={14} /> Opponent</span>
              <span className="flex items-center gap-1 text-gray-400"><Lock size={14} /> years in prison</span>
            </div>
          </div>
          {/* Column headers */}
          <div className="bg-gray-800 p-3 text-center text-sm font-semibold text-gray-100 flex items-center justify-center gap-2">
            <ShieldCheck className="text-emerald-400" size={16} /> Opponent: Cooperate
          </div>
          <div className="bg-gray-800 p-3 text-center text-sm font-semibold text-gray-100 flex items-center justify-center gap-2">
            <Gavel className="text-amber-400" size={16} /> Opponent: Defect
          </div>

          {/* Row: You Cooperate */}
          <div className="bg-gray-800 p-3 text-left text-sm font-semibold text-gray-100 flex items-center gap-2">
            <ShieldCheck className="text-emerald-400" size={16} /> You: Cooperate
          </div>
          {/* Cell: C, C */}
          <div className="p-4 border-t border-l border-gray-800 flex flex-col items-center justify-center bg-emerald-950">
            <div className="text-sm font-medium text-emerald-300">Both cooperate</div>
            <div className="mt-1 flex items-center gap-4 text-xs text-emerald-300">
              <span className="flex items-center gap-1"><User size={14} /><Lock size={14} />2y</span>
              <span className="flex items-center gap-1"><UserCircle size={14} /><Lock size={14} />2y</span>
            </div>
          </div>
          {/* Cell: C, D */}
          <div className="p-4 border-t border-l border-gray-800 flex flex-col items-center justify-center bg-amber-950">
            <div className="text-sm font-medium text-amber-300">They exploit</div>
            <div className="mt-1 flex items-center gap-4 text-xs text-amber-300">
              <span className="flex items-center gap-1"><User size={14} /><Lock size={14} />8y</span>
              <span className="flex items-center gap-1"><UserCircle size={14} /><Lock size={14} />0y</span>
            </div>
          </div>

          {/* Row: You Defect */}
          <div className="bg-gray-800 p-3 text-left text-sm font-semibold text-gray-100 flex items-center gap-2">
            <Gavel className="text-amber-400" size={16} /> You: Defect
          </div>
          {/* Cell: D, C */}
          <div className="p-4 border-t border-l border-gray-800 flex flex-col items-center justify-center bg-amber-950">
            <div className="text-sm font-medium text-amber-300">You exploit</div>
            <div className="mt-1 flex items-center gap-4 text-xs text-amber-300">
              <span className="flex items-center gap-1"><User size={14} /><Lock size={14} />0y</span>
              <span className="flex items-center gap-1"><UserCircle size={14} /><Lock size={14} />8y</span>
            </div>
          </div>
          {/* Cell: D, D */}
          <div className="p-4 border-t border-l border-gray-800 flex flex-col items-center justify-center bg-rose-950">
            <div className="text-sm font-medium text-rose-300">Both defect</div>
            <div className="mt-1 flex items-center gap-4 text-xs text-rose-300">
              <span className="flex items-center gap-1"><User size={14} /><Lock size={14} />10y</span>
              <span className="flex items-center gap-1"><UserCircle size={14} /><Lock size={14} />10y</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}