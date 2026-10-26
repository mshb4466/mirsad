// ===========================================================================
// Mirsad Levels (Gamma -> ES) — دراسة Sierra Chart تقرأ مستويات مرصاد مباشرة من الإنترنت
// وترسلها خطوطاً أفقية على شارت ES بالنمط واللون والسماكة بحسب القوة، وتحدّثها وتحذف القديم تلقائياً.
//
// المصدر: ملف gamma/levels_es.csv في مستودع مرصاد (يُحدَّث مع كل لقطة جاما). لا مفاتيح ولا أسرار فيه.
// الأعمدة:  price,label,kind,strength,color,style,width     (السطر الأول: asof_utc,...,basis,...)
//
// ملاحظة: هذا الملف لم يُجرَّب على Sierra Chart نفسه (المنصة غير متاحة في بيئة التطوير). إن ظهر خطأ ترجمة
// فأرسل نصّه كما هو لتصحيحه.
// ===========================================================================
#include "sierrachart.h"
#include <string>
#include <vector>
#include <sstream>
#include <cstdlib>
#include <ctime>
#include <cstring>
#include <cstdio>

SCDLLName("Mirsad Levels")

static const int MIRSAD_BASE_LINE = 91000000;   // أرقام خطوط المرصاد (ثابتة لتعديلها بدل تكرارها)
static const int MIRSAD_MAX_LINES = 120;

struct MirsadLevel
{
	double Price;
	std::string Label;
	std::string Kind;
	std::string Strength;
	unsigned int Rgb;     // 0xRRGGBB
	std::string Style;    // solid | dash | dot
	int Width;
};

static std::vector<std::string> SplitCSV(const std::string& line)
{
	std::vector<std::string> out;
	std::string cur;
	for (size_t i = 0; i < line.size(); ++i)
	{
		if (line[i] == ',') { out.push_back(cur); cur.clear(); }
		else if (line[i] != '\r') cur.push_back(line[i]);
	}
	out.push_back(cur);
	return out;
}

static double HeaderAgeMinutes(const std::string& header)
{
	// asof_utc,2026-10-26T14:00:00+00:00,basis,...
	std::vector<std::string> p = SplitCSV(header);
	if (p.size() < 2) return -1;
	int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
	if (sscanf(p[1].c_str(), "%d-%d-%dT%d:%d:%d", &y, &mo, &d, &h, &mi, &s) != 6) return -1;
	struct tm t; memset(&t, 0, sizeof(t));
	t.tm_year = y - 1900; t.tm_mon = mo - 1; t.tm_mday = d; t.tm_hour = h; t.tm_min = mi; t.tm_sec = s;
	time_t asof = _mkgmtime(&t);
	if (asof == (time_t)-1) return -1;
	return difftime(time(NULL), asof) / 60.0;
}

static void ParseLevels(const std::string& text, std::vector<MirsadLevel>& out, double& ageMin)
{
	out.clear(); ageMin = -1;
	std::istringstream in(text);
	std::string line; int n = 0;
	while (std::getline(in, line))
	{
		if (line.empty() || line == "\r") continue;
		++n;
		if (n == 1) { ageMin = HeaderAgeMinutes(line); continue; }
		if (line.compare(0, 5, "price") == 0) continue;
		std::vector<std::string> c = SplitCSV(line);
		if (c.size() < 7) continue;
		MirsadLevel L;
		L.Price = atof(c[0].c_str());
		if (L.Price <= 0) continue;
		L.Label = c[1]; L.Kind = c[2]; L.Strength = c[3];
		L.Rgb = (unsigned int)strtoul(c[4].c_str(), NULL, 16);
		L.Style = c[5]; L.Width = atoi(c[6].c_str());
		if (L.Width < 1) L.Width = 1;
		out.push_back(L);
	}
}

SCSFExport scsf_MirsadLevels(SCStudyInterfaceRef sc)
{
	SCInputRef Url = sc.Input[0];
	SCInputRef RefreshSec = sc.Input[1];
	SCInputRef ShowSpy = sc.Input[2];
	SCInputRef ShowMedium = sc.Input[3];
	SCInputRef ShowPeaks = sc.Input[4];
	SCInputRef MaxAgeMin = sc.Input[5];

	if (sc.SetDefaults)
	{
		sc.GraphName = "Mirsad Levels (Gamma to ES)";
		sc.StudyDescription = "Reads Mirsad gamma levels (ES prices) from the internet and draws them as horizontal lines.";
		sc.AutoLoop = 0;
		sc.GraphRegion = 0;
		sc.UpdateAlways = 1;
		sc.FreeDLL = 0;

		Url.Name = "CSV URL";
		Url.SetString("https://raw.githubusercontent.com/mshb4466/mirsad/main/gamma/levels_es.csv");
		RefreshSec.Name = "Refresh every (seconds)"; RefreshSec.SetInt(60); RefreshSec.SetIntLimits(15, 3600);
		ShowSpy.Name = "Show SPY levels"; ShowSpy.SetYesNo(1);
		ShowMedium.Name = "Show medium peaks (dashed)"; ShowMedium.SetYesNo(1);
		ShowPeaks.Name = "Show peaks/troughs (otherwise walls and flip only)"; ShowPeaks.SetYesNo(1);
		MaxAgeMin.Name = "Mark labels [OLD] after (minutes)"; MaxAgeMin.SetInt(45); MaxAgeMin.SetIntLimits(5, 100000);
		return;
	}

	int& State = sc.GetPersistentInt(1);            // 0 = idle, 1 = waiting for response
	int& DrawnCount = sc.GetPersistentInt(2);
	double& LastRequest = sc.GetPersistentDouble(1);

	if (sc.LastCallToFunction)
	{
		for (int i = 0; i < MIRSAD_MAX_LINES; ++i)
			sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_CHARTDRAWING, MIRSAD_BASE_LINE + i);
		return;
	}

	const double nowD = sc.CurrentSystemDateTime.GetAsDouble();
	if (State == 0 && (LastRequest == 0 || (nowD - LastRequest) * 86400.0 >= RefreshSec.GetInt()))
	{
		if (sc.MakeHTTPRequest(Url.GetString()))
		{
			State = 1; LastRequest = nowD;
		}
		else
		{
			LastRequest = nowD;
			sc.AddMessageToLog("Mirsad Levels: HTTP request could not be started.", 0);
		}
		return;
	}

	if (State == 1 && sc.HTTPResponse != "")
	{
		State = 0;
		std::vector<MirsadLevel> levels; double ageMin = -1;
		ParseLevels(sc.HTTPResponse.GetChars(), levels, ageMin);
		if (levels.empty())
		{
			sc.AddMessageToLog("Mirsad Levels: response had no levels (kept existing lines).", 0);
			return;
		}
		const bool old = (ageMin >= 0 && ageMin > MaxAgeMin.GetInt());
		int idx = 0;
		for (size_t i = 0; i < levels.size() && idx < MIRSAD_MAX_LINES; ++i)
		{
			const MirsadLevel& L = levels[i];
			if (!ShowSpy.GetYesNo() && L.Label.compare(0, 3, "SPY") == 0) continue;
			if (L.Kind == "peak")
			{
				if (!ShowPeaks.GetYesNo()) continue;
				if (L.Strength == "medium" && !ShowMedium.GetYesNo()) continue;
			}
			s_UseTool Tool;
			Tool.Clear();
			Tool.ChartNumber = sc.ChartNumber;
			Tool.DrawingType = DRAWING_HORIZONTALLINE;
			Tool.LineNumber = MIRSAD_BASE_LINE + idx;
			Tool.AddMethod = UTAM_ADD_OR_ADJUST;
			Tool.BeginValue = (float)L.Price;
			const unsigned int r = (L.Rgb >> 16) & 0xFF, g = (L.Rgb >> 8) & 0xFF, b = L.Rgb & 0xFF;
			Tool.Color = RGB(r, g, b);
			Tool.LineWidth = L.Width;
			Tool.LineStyle = (L.Style == "dash") ? LINESTYLE_DASH : (L.Style == "dot") ? LINESTYLE_DOT : LINESTYLE_SOLID;
			std::string label = L.Label; if (old) label += " [OLD]";
			Tool.Text = label.c_str();
			Tool.AddAsUserDrawnDrawing = 0;
			sc.UseTool(Tool);
			++idx;
		}
		// احذف الخطوط الزائدة من التحديث السابق (إن قلّ العدد)
		for (int i = idx; i < DrawnCount; ++i)
			sc.DeleteACSChartDrawing(sc.ChartNumber, TOOL_DELETE_CHARTDRAWING, MIRSAD_BASE_LINE + i);
		DrawnCount = idx;
	}
	else if (State == 1 && (nowD - LastRequest) * 86400.0 > 30)
	{
		State = 0;   // انتهت المهلة؛ أعد المحاولة في الدورة القادمة
	}
}
